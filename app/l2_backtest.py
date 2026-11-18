"""L2 event-driven backtest over MarketHistoryWriter gzip JSONL.

Replays depth snapshots in timestamp order. Fills walk the visible book with
Almgren-style impact — usable for imbalance / wall research that OHLCV cannot do.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from heapq import merge
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
    notes: str = (
        "Multi-symbol event-time replay reconstructs persistent L2 pressure, "
        "spoof persistence, aggressor trade flow, closed-candle indicators and "
        "BTC/ETH macro gates. Public depth cannot reveal true queue position, "
        "hidden liquidity or exact historical fills; results remain simulated."
    )


def _best(levels: list) -> tuple[float, float] | None:
    if not levels:
        return None
    row = levels[0]
    if isinstance(row, (list, tuple)) and len(row) >= 2:
        return float(row[0]), float(row[1])
    return None


def _walk_book(side: str, levels: list, quantity: float, *, impact_bps: float = 0.0) -> tuple[float, float]:
    remaining = quantity
    cost = 0.0
    filled = 0.0
    for row in levels or []:
        if remaining <= 0:
            break
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        px, qty = float(row[0]), float(row[1])
        if px <= 0 or qty <= 0:
            continue
        take = min(remaining, qty)
        adj = px * (1.0 + impact_bps / 10_000.0) if side == "buy" else px * (1.0 - impact_bps / 10_000.0)
        cost += adj * take
        filled += take
        remaining -= take
    if filled <= 0:
        return 0.0, 0.0
    return cost / filled, filled


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
    last_bid_levels: list | None = None
    market_context = ReplayMarketContext([primary_symbol] if primary_symbol else [])
    blocked_candidate_samples: list[dict[str, Any]] = []
    quote_samples: list[dict[str, Any]] = []
    sources = [path, *(context_paths or {}).values()]
    events = merge(
        *(replay_market_history(source) for source in sources),
        key=lambda item: int(item["timestamp_ns"]),
    )
    active_symbol = (primary_symbol or "").lower()

    for event in events:
        result.events_seen += 1
        payload = event.get("payload") or event
        ts = int(event.get("timestamp_ns") or payload.get("timestamp_ns") or 0)
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

        bb = payload.get("best_bid") or payload.get("bids") or []
        ba = payload.get("best_ask") or payload.get("asks") or []
        if isinstance(bb, list) and bb and isinstance(bb[0], (list, tuple)):
            best_b = _best(bb)
        elif isinstance(bb, (list, tuple)) and len(bb) >= 2 and not isinstance(bb[0], (list, tuple)):
            best_b = (float(bb[0]), float(bb[1]))
        else:
            best_b = _best(bb) if isinstance(bb, list) else None
        if isinstance(ba, list) and ba and isinstance(ba[0], (list, tuple)):
            best_a = _best(ba)
        elif isinstance(ba, (list, tuple)) and len(ba) >= 2 and not isinstance(ba[0], (list, tuple)):
            best_a = (float(ba[0]), float(ba[1]))
        else:
            best_a = _best(ba) if isinstance(ba, list) else None
        if not best_b or not best_a:
            continue
        bid, bid_qty = best_b
        ask, ask_qty = best_a
        last_bid = bid
        if bid <= 0 or ask < bid:
            continue
        quote_samples.append({"timestamp_ns": ts, "bid": bid, "ask": ask})
        if not result.equity_curve:
            result.equity_curve.append({
                "timestamp_ns": ts, "equity": cfg.starting_cash_usdt,
                "mid": (bid + ask) / 2, "score": 0.0, "phase": "initial",
            })
        bids = payload.get("bids") if isinstance(payload.get("bids"), list) else [[bid, bid_qty]]
        asks = payload.get("asks") if isinstance(payload.get("asks"), list) else [[ask, ask_qty]]
        last_bid_levels = bids
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
                    result.profit_lock_exits += 1
            if reason:
                qty = paper.base_quantity
                stressed_exit = reason in {"stop_loss", "trailing_stop", "time_stop"}
                fill = sim.fill(
                    side="sell", reference_price=bid, quantity=qty,
                    book_levels=bids or [[bid, bid_qty]], stress=stressed_exit,
                )
                if fill.filled_quantity <= 0:
                    fill = sim.fill(side="sell", reference_price=bid, quantity=qty, stress=stressed_exit)
                if fill.filled_quantity > 0:
                    trade = paper.sell_quantity(
                        quantity=fill.filled_quantity, price=fill.fill_price,
                        reason=f"l2_{reason};slippage_bps={fill.slippage_bps:.2f};latency_ms={fill.latency_ms}",
                    )
                    if trade:
                        result.trades.append({**trade, "timestamp_ns": ts})
                        result.exits += 1
                        if paper.base_quantity <= 1e-12:
                            result.closed_positions += 1
                        peak = 0.0
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
                qty = sizing.notional_usdt / ask
                fill = sim.fill(
                    side="buy", reference_price=ask, quantity=qty,
                    book_levels=asks or [[ask, ask_qty]],
                )
                if fill.filled_quantity <= 0:
                    fill = sim.fill(side="buy", reference_price=ask, quantity=qty)
                notional = fill.filled_quantity * fill.fill_price
                if notional > 0:
                    trade = paper.buy(
                        notional_usdt=notional, price=fill.fill_price,
                        reason=f"l2_entry;score={analysis.score:.2f};slippage_bps={fill.slippage_bps:.2f};latency_ms={fill.latency_ms}",
                    )
                    result.trades.append({**trade, "timestamp_ns": ts})
                    result.entries += 1
                    peak = fill.fill_price
                    confirmations = 0

        snap = paper.snapshot(bid)
        result.equity_curve.append({
            "timestamp_ns": ts, "equity": snap["equity_usdt"],
            "mid": (bid + ask) / 2, "score": analysis.score,
        })

    # Close any remaining position at the final executable bid so reported
    # performance includes the exit fee, slippage and visible-book impact.
    end_liquidated = False
    if paper.base_quantity > 1e-12 and last_bid is not None and last_bid > 0:
        final_quantity = paper.base_quantity
        final_fill = sim.fill(
            side="sell", reference_price=last_bid, quantity=final_quantity,
            book_levels=last_bid_levels, stress=True,
        )
        if final_fill.filled_quantity > 0:
            final_trade = paper.sell_quantity(
                quantity=final_fill.filled_quantity,
                price=final_fill.fill_price,
                reason=(
                    "l2_end_of_sample_liquidation;"
                    f"slippage_bps={final_fill.slippage_bps:.2f};"
                    f"latency_ms={final_fill.latency_ms}"
                ),
            )
            if final_trade:
                result.trades.append({**final_trade, "timestamp_ns": ts})
                result.exits += 1
                if paper.base_quantity <= 1e-12:
                    result.closed_positions += 1
                    end_liquidated = True

    snap = paper.snapshot(last_bid)
    if end_liquidated:
        result.equity_curve.append({
            "timestamp_ns": ts, "equity": snap["equity_usdt"],
            "mid": last_bid, "score": 0.0,
            "phase": "end_of_sample_liquidation",
        })
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
                for key in ("side", "price", "quantity", "pnl_usdt", "fee_usdt", "reason", "timestamp_ns")
            }
            for trade in result.trades
        ],
        "notes": result.notes,
    }
