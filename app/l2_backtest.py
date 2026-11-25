"""L2 event-driven backtest over MarketHistoryWriter gzip JSONL.

Replays depth snapshots in timestamp order. Fills walk the visible book with
Almgren-style impact — usable for imbalance / wall research that OHLCV cannot do.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from heapq import merge
from math import isfinite
from pathlib import Path
from typing import Any

from app.market_history import replay_market_history
from app.opportunity_audit import audit_blocked_candidates
from app.profit_lock import net_profit_lock_reason
from app.replay_context import ReplayMarketContext
from app.paper import PaperExecutor
from app.portfolio import size_from_free_cash
from app.simulation import ExecutionSimulator
from app.strategy import PriceWindow, analyze_market, entry_signal_from_analysis, exit_reason


@dataclass(slots=True)
class L2BacktestConfig:
    starting_cash_usdt: float = 1000.0
    fee_rate: float = 0.001
    order_size_usdt: float = 25.0
    max_order_size_usdt: float = 50.0
    imbalance_threshold: float = 0.70
    entry_min_score: float = 0.55
    signal_confirmations: int = 3
    take_profit_pct: float = 1.0
    stop_loss_pct: float = 0.5
    trailing_stop_pct: float = 0.35
    target_price: float | None = None
    slippage_bps: float = 3.0
    impact_coefficient: float = 0.1
    latency_ms: int = 50
    partial_fill_probability: float = 0.0
    seed: int = 0
    min_order_usdt: float = 5.0
    stop_stress_multiplier: float = 2.5
    stop_tail_bps: float = 8.0
    max_execution_wait_ms: int = 2000


@dataclass
class L2BacktestResult:
    trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    final_equity: float = 0.0
    final_cash: float = 0.0
    realized_pnl: float = 0.0
    trade_count: int = 0
    events_seen: int = 0
    signals: int = 0
    entries: int = 0
    exits: int = 0
    closed_positions: int = 0
    final_open_quantity: float = 0.0
    trade_events: int = 0
    context_trade_events: int = 0
    kline_events: int = 0
    profit_lock_exits: int = 0
    blocked_candidates: int = 0
    blocker_counts: dict[str, int] = field(default_factory=dict)
    opportunity_audit: dict[str, Any] = field(default_factory=dict)
    simulated_orders: int = 0
    unfilled_orders: int = 0
    pending_orders_at_end: int = 0
    invalid_depth_frames: int = 0
    notes: str = (
        "Multi-symbol event-time replay reconstructs persistent L2 pressure, "
        "spoof persistence, aggressor trade flow, closed-candle indicators and "
        "BTC/ETH macro gates. Public depth cannot reveal true queue position, "
        "hidden liquidity or exact historical fills. Orders use the first eligible "
        "observed primary depth after sampled latency. Ending positions are marked "
        "to the last observed bid, not liquidated."
    )


@dataclass(frozen=True, slots=True)
class _ReplayIntent:
    side: str
    decision_ns: int
    latency_ms: int
    reason: str
    quantity: float
    quote_budget: float = 0.0
    stress: bool = False
    profit_lock: bool = False

    @property
    def arrival_ns(self) -> int:
        return self.decision_ns + self.latency_ms * 1_000_000


def _recorded_levels(payload: dict, key: str) -> list[tuple[float, float]]:
    values = payload.get(key)
    if not isinstance(values, list):
        return []
    levels: dict[float, float] = {}
    for row in values:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            return []
        try:
            price, qty = float(row[0]), float(row[1])
        except (TypeError, ValueError, IndexError, KeyError, OverflowError):
            return []
        if not isfinite(price) or not isfinite(qty) or price <= 0 or qty < 0 or price in levels:
            return []
        levels[price] = qty
    return sorted(((px, qty) for px, qty in levels.items() if qty > 0), reverse=key == "bids")


def run_l2_backtest(
    path: str | Path,
    cfg: L2BacktestConfig | None = None,
    *,
    context_paths: dict[str, str | Path] | None = None,
    primary_symbol: str | None = None,
) -> L2BacktestResult:
    if context_paths and not primary_symbol:
        raise ValueError("primary_symbol is required when replaying multiple symbol files")
    cfg = cfg or L2BacktestConfig()
    if type(cfg.max_execution_wait_ms) is not int or cfg.max_execution_wait_ms < 0:
        raise ValueError("max_execution_wait_ms must be a nonnegative integer")
    paper = PaperExecutor(cfg.starting_cash_usdt, cfg.fee_rate)
    sim = ExecutionSimulator(
        slippage_bps=cfg.slippage_bps,
        latency_ms=cfg.latency_ms,
        partial_fill_probability=cfg.partial_fill_probability,
        seed=cfg.seed,
        impact_coefficient=cfg.impact_coefficient,
        stop_stress_multiplier=cfg.stop_stress_multiplier,
        stop_tail_bps=cfg.stop_tail_bps,
        symbol=primary_symbol,
    )
    # Match the live 0.5s sample cadence, but use replay event timestamps.
    pw = PriceWindow(maxlen=1200, sample_interval_seconds=0.5)
    result = L2BacktestResult()
    confirmations = 0
    peak = 0.0
    last_bid: float | None = None
    pending: _ReplayIntent | None = None
    market_context = ReplayMarketContext([primary_symbol] if primary_symbol else [])
    blocked_candidate_samples: list[dict[str, Any]] = []
    quote_samples: list[dict[str, Any]] = []
    sources = [path, *(context_paths or {}).values()]
    events = merge(
        *(replay_market_history(source) for source in sources),
        key=lambda item: int(item["timestamp_ns"]),
    )
    active_symbol = (primary_symbol or "").lower()
    last_event_ns = -1

    def execute(
        intent: _ReplayIntent, ts: int, bids: list, asks: list,
    ) -> None:
        nonlocal peak
        levels = asks if intent.side == "buy" else bids
        if not levels or ts - intent.arrival_ns > cfg.max_execution_wait_ms * 1_000_000:
            result.unfilled_orders += 1
            return
        fill = sim.fill(
            side=intent.side, reference_price=levels[0][0], quantity=intent.quantity,
            book_levels=levels, stress=intent.stress, sampled_latency_ms=intent.latency_ms,
        )
        if fill.filled_quantity <= 0 or fill.fill_price <= 0:
            result.unfilled_orders += 1
            return
        label = f"{intent.reason};slippage_bps={fill.slippage_bps:.2f};latency_ms={fill.latency_ms}"
        if intent.side == "buy":
            notional = min(intent.quote_budget, fill.fill_price * fill.filled_quantity)
            trade = paper.buy(notional_usdt=notional, price=fill.fill_price, reason=label)
            result.entries += 1
            peak = fill.fill_price
        else:
            trade = paper.sell_quantity(quantity=fill.filled_quantity, price=fill.fill_price, reason=label)
            if not trade:
                result.unfilled_orders += 1
                return
            result.exits += 1
            if intent.profit_lock:
                result.profit_lock_exits += 1
            if paper.base_quantity <= 1e-12:
                result.closed_positions += 1
                peak = 0.0
        result.trades.append({
            **trade,
            "timestamp_ns": ts,
            "decision_timestamp_ns": intent.decision_ns,
            "arrival_timestamp_ns": intent.arrival_ns,
        })

    for event in events:
        result.events_seen += 1
        payload = event.get("payload") or event
        ts = event["timestamp_ns"]
        if type(ts) is not int or ts < 0 or ts < last_event_ns:
            raise ValueError("L2 replay requires nonnegative chronological integer timestamps")
        last_event_ns = ts
        event_time = ts / 1_000_000_000.0
        event_type = str(event.get("event_type") or "")

        if event_type == "trade":
            trade_symbol = str(payload.get("symbol") or "").lower()
            if active_symbol and trade_symbol != active_symbol:
                result.context_trade_events += 1
                continue
            try:
                market_context.update_trade(payload, event_time)
                result.trade_events += 1
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            continue

        if event_type == "kline":
            try:
                if payload.get("closed") is True:
                    market_context.update_kline(payload, event_time)
                    result.kline_events += 1
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            continue

        if event_type != "depth":
            continue

        event_symbol = str(payload.get("symbol") or active_symbol).lower()
        if not active_symbol:
            active_symbol = event_symbol
        if event_symbol != active_symbol:
            # Macro gates use BTC/ETH closed candles only; their trade/depth
            # streams are deliberately not replayed into the primary instrument.
            continue

        bids = _recorded_levels(payload, "bids")
        asks = _recorded_levels(payload, "asks")
        if not bids or not asks or bids[0][0] >= asks[0][0] or payload.get("synchronized") is False:
            result.invalid_depth_frames += 1
            confirmations = 0
            if pending is not None:
                # A known data break invalidates the execution observation, even
                # if the order's release would be after this damaged frame.
                result.unfilled_orders += 1
                pending = None
            continue
        bid, bid_qty = bids[0]
        ask, ask_qty = asks[0]
        last_bid = bid
        quote_samples.append({"timestamp_ns": ts, "bid": bid, "ask": ask})
        if not result.equity_curve:
            result.equity_curve.append({
                "timestamp_ns": ts, "equity": cfg.starting_cash_usdt,
                "mid": (bid + ask) / 2, "score": 0.0, "phase": "initial",
            })
        analysis = analyze_market(
            bid=bid, ask=ask, bid_qty=bid_qty, ask_qty=ask_qty,
            price_window=pw, imbalance_threshold=cfg.imbalance_threshold,
            target_price=cfg.target_price, bids=bids, asks=asks,
            timestamp=event_time,
        )

        depth_context = market_context.update_depth(
            payload, event_time, imbalance=analysis.imbalance,
            micro_premium_bps=analysis.micro_premium_bps,
        )
        indicator = market_context.indicator_snapshot(active_symbol, event_time)
        if indicator.ready:
            if indicator.trend_bias == "bullish" and indicator.momentum_bias == "bullish":
                analysis.score = min(1.0, analysis.score + 0.08)
                analysis.reasons.append("indicator_trend_and_momentum_bullish")
            elif indicator.trend_bias == "bearish" or indicator.momentum_bias == "bearish":
                analysis.score = max(-1.0, analysis.score - 0.12)
                analysis.reasons.append("indicator_bearish_context")
        if depth_context.spoof_score >= 0.70:
            analysis.score *= max(0.20, 1.0 - depth_context.spoof_score)
            analysis.reasons.append(f"transient_depth_risk={depth_context.spoof_score:.2f}")

        if pending is not None:
            if ts >= pending.arrival_ns:
                execute(pending, ts, bids, asks)
                pending = None
            result.equity_curve.append({
                "timestamp_ns": ts, "equity": paper.snapshot(bid)["equity_usdt"],
                "mid": (bid + ask) / 2, "score": analysis.score,
            })
            continue

        if paper.base_quantity > 0 and paper.average_entry_price > 0:
            if peak <= 0:
                peak = bid
            else:
                peak = max(peak, bid)
            reason = exit_reason(
                bid=bid, average_entry=paper.average_entry_price,
                take_profit_pct=cfg.take_profit_pct, stop_loss_pct=cfg.stop_loss_pct,
                trailing_stop_pct=cfg.trailing_stop_pct, peak_price=peak,
                target_price=cfg.target_price,
            )
            profit_lock_reason = None
            if reason is None:
                trade_flow = market_context.trades[active_symbol].snapshot(now=event_time)
                book_flow = depth_context.book_flow
                profit_lock_reason = net_profit_lock_reason(
                    bid=bid,
                    average_entry=paper.average_entry_price,
                    peak_price=peak,
                    fee_rate=cfg.fee_rate,
                    slippage_bps_per_side=cfg.slippage_bps,
                    momentum_1m_bps=analysis.momentum_1m_bps,
                    momentum_5m_bps=analysis.momentum_5m_bps,
                    trade_flow={
                        "ready": trade_flow.ready,
                        "age_seconds": trade_flow.age_seconds,
                        "delta_ratio": trade_flow.delta_ratio,
                    },
                    book_flow={
                        "ready": book_flow.ready,
                        "pressure": book_flow.pressure,
                    },
                )
                if profit_lock_reason:
                    reason = profit_lock_reason
            if reason:
                stressed_exit = reason in {"stop_loss", "trailing_stop", "time_stop"}
                pending = _ReplayIntent(
                    "sell", ts, sim.sample_latency_ms(side="sell", stress=stressed_exit),
                    f"l2_{reason}", paper.base_quantity, stress=stressed_exit,
                    profit_lock=profit_lock_reason is not None,
                )
                result.simulated_orders += 1
                if pending.latency_ms == 0:
                    execute(pending, ts, bids, asks)
                    pending = None
            snap = paper.snapshot(bid)
            result.equity_curve.append({
                "timestamp_ns": ts, "equity": snap["equity_usdt"],
                "mid": (bid + ask) / 2, "score": analysis.score,
            })
            continue

        signal = entry_signal_from_analysis(analysis, min_score=cfg.entry_min_score)
        if signal:
            result.signals += 1
            blockers, _context_details = market_context.entry_blockers(
                active_symbol, event_time, depth_context,
            )
            if blockers:
                result.blocked_candidates += 1
                for blocker in blockers:
                    result.blocker_counts[blocker] = result.blocker_counts.get(blocker, 0) + 1
                blocked_candidate_samples.append({
                    "timestamp_ns": ts,
                    "entry_ask": ask,
                    "blockers": list(blockers),
                })
                signal = None
        if signal:
            confirmations += 1
        else:
            confirmations = 0
        if signal and confirmations >= cfg.signal_confirmations and paper.base_quantity <= 0:
            sizing = size_from_free_cash(
                free_usdt=paper.cash_usdt, allocation_fraction=0.8, fee_rate=cfg.fee_rate,
                max_order_usdt=min(cfg.order_size_usdt, cfg.max_order_size_usdt),
                min_order_usdt=cfg.min_order_usdt,
            )
            if sizing.notional_usdt > 0:
                pending = _ReplayIntent(
                    "buy", ts, sim.sample_latency_ms(side="buy"),
                    f"l2_entry;score={analysis.score:.2f}",
                    sizing.notional_usdt / ask, quote_budget=sizing.notional_usdt,
                )
                result.simulated_orders += 1
                confirmations = 0
                if pending.latency_ms == 0:
                    execute(pending, ts, bids, asks)
                    pending = None

        snap = paper.snapshot(bid)
        result.equity_curve.append({
            "timestamp_ns": ts, "equity": snap["equity_usdt"],
            "mid": (bid + ask) / 2, "score": analysis.score,
        })

    result.pending_orders_at_end = int(pending is not None)
    snap = paper.snapshot(last_bid)
    result.opportunity_audit = audit_blocked_candidates(
        blocked_candidate_samples,
        quote_samples,
        fee_rate=cfg.fee_rate,
        slippage_bps_per_side=cfg.slippage_bps,
    )
    result.final_equity = float(snap["equity_usdt"])
    result.final_cash = float(snap["cash_usdt"])
    result.realized_pnl = float(snap["realized_pnl_usdt"])
    result.final_open_quantity = float(paper.base_quantity)
    result.trade_count = len(result.trades)
    return result


def summarize_l2_result(result: L2BacktestResult) -> dict[str, Any]:
    start = result.equity_curve[0]["equity"] if result.equity_curve else result.final_equity
    ret = (result.final_equity / start - 1.0) if start else 0.0
    peak = start
    max_drawdown = 0.0
    for point in result.equity_curve:
        equity = float(point["equity"])
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    closed = [
        t for t in result.trades
        if str(t.get("side", "")).lower() == "sell"
        and t.get("accounting_complete", True) is True
        and t.get("pnl_usdt") is not None
    ]
    pnls = [float(t["pnl_usdt"]) for t in closed]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    fees = sum(float(t.get("fee_usdt") or 0) for t in result.trades)
    return {
        "events_seen": result.events_seen,
        "trade_events": result.trade_events,
        "context_trade_events": result.context_trade_events,
        "kline_events": result.kline_events,
        "profit_lock_exits": result.profit_lock_exits,
        "blocked_candidates": result.blocked_candidates,
        "blocker_counts": dict(sorted(result.blocker_counts.items())),
        "blocked_opportunity_audit": result.opportunity_audit,
        "signals": result.signals,
        "entries": result.entries,
        "exits": result.exits,
        "trade_count": result.trade_count,
        "closed_position_count": result.closed_positions,
        "exit_fill_count": len(closed),
        "final_open_quantity": result.final_open_quantity,
        "simulated_orders": result.simulated_orders,
        "unfilled_orders": result.unfilled_orders,
        "pending_orders_at_end": result.pending_orders_at_end,
        "invalid_depth_frames": result.invalid_depth_frames,
        "ending_valuation": "mark_to_observed_bid_no_forced_close",
        "win_rate_pct_per_exit_fill": (len(wins) / len(pnls) * 100) if pnls else 0.0,
        "expectancy_usdt_per_exit_fill": (sum(pnls) / len(pnls)) if pnls else 0.0,
        "profit_factor_per_exit_fill": (gross_profit / gross_loss) if gross_loss > 0 else None,
        "fees_paid_usdt": fees,
        "max_drawdown_pct": max_drawdown * 100,
        "final_equity": result.final_equity,
        "realized_pnl": result.realized_pnl,
        "return_pct": ret * 100,
        "trade_log": [
            {
                key: trade.get(key)
                for key in (
                    "side", "price", "quantity", "pnl_usdt", "fee_usdt", "reason",
                    "timestamp_ns", "decision_timestamp_ns", "arrival_timestamp_ns",
                )
            }
            for trade in result.trades
        ],
        "notes": result.notes,
    }
