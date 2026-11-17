"""L2 event-driven backtest over MarketHistoryWriter gzip JSONL.

Replays depth snapshots in timestamp order. Fills walk the visible book with
Almgren-style impact — usable for imbalance / wall research that OHLCV cannot do.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.events import TradeTick
from app.market_history import replay_market_history
from app.market_indicators import Candle, MarketIndicatorTracker
from app.profit_lock import net_profit_lock_reason
from app.trade_flow import TradeFlowTracker
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
    kline_events: int = 0
    profit_lock_exits: int = 0
    notes: str = (
        "L2 replay uses recorded visible book only; cancelled liquidity and true "
        "queue position are not recoverable from public depth diffs. Entry scoring "
        "uses the recorded depth stream; full engine-side entry gates are not yet "
        "reconstructed. Fee-aware profit-lock exits use recorded trades and klines."
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


def run_l2_backtest(path: str | Path, cfg: L2BacktestConfig | None = None) -> L2BacktestResult:
    cfg = cfg or L2BacktestConfig()
    paper = PaperExecutor(cfg.starting_cash_usdt, cfg.fee_rate)
    sim = ExecutionSimulator(
        slippage_bps=cfg.slippage_bps,
        latency_ms=cfg.latency_ms,
        partial_fill_probability=cfg.partial_fill_probability,
        seed=cfg.seed,
        impact_coefficient=cfg.impact_coefficient,
    )
    # Replay timestamps are event-time; retain 10 minutes at the 0.5s sample cadence.
    pw = PriceWindow(maxlen=1200)
    result = L2BacktestResult()
    confirmations = 0
    peak = 0.0
    last_bid: float | None = None
    indicator_tracker = MarketIndicatorTracker()
    trade_tracker = TradeFlowTracker(window_seconds=10.0, min_trades=20, max_age_seconds=2.5)

    for event in replay_market_history(path):
        result.events_seen += 1
        payload = event.get("payload") or event
        ts = int(event.get("timestamp_ns") or payload.get("timestamp_ns") or 0)
        event_time = ts / 1_000_000_000.0
        event_type = str(event.get("event_type") or "")

        if event_type == "trade":
            try:
                trade_tracker.update(TradeTick(
                    symbol=str(payload.get("symbol") or "").lower(),
                    price=float(payload["price"]),
                    quantity=float(payload["quantity"]),
                    buyer_is_maker=bool(payload["buyer_is_maker"]),
                    received_at=datetime.fromtimestamp(event_time, timezone.utc),
                ), now=event_time)
                result.trade_events += 1
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            continue

        if event_type == "kline":
            try:
                if payload.get("closed") is True:
                    indicator_tracker.update(Candle(
                        symbol=str(payload.get("symbol") or "").lower(),
                        interval=str(payload["interval"]),
                        open_time=int(payload["open_time"]),
                        open=float(payload["open"]),
                        high=float(payload["high"]),
                        low=float(payload["low"]),
                        close=float(payload["close"]),
                        volume=float(payload.get("volume") or 0.0),
                        closed=True,
                        received_at=event_time,
                    ))
                    result.kline_events += 1
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            continue

        if event_type != "depth":
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
        if not result.equity_curve:
            result.equity_curve.append({
                "timestamp_ns": ts, "equity": cfg.starting_cash_usdt,
                "mid": (bid + ask) / 2, "score": 0.0, "phase": "initial",
            })
        bids = payload.get("bids") if isinstance(payload.get("bids"), list) else [[bid, bid_qty]]
        asks = payload.get("asks") if isinstance(payload.get("asks"), list) else [[ask, ask_qty]]
        analysis = analyze_market(
            bid=bid, ask=ask, bid_qty=bid_qty, ask_qty=ask_qty,
            price_window=pw, imbalance_threshold=cfg.imbalance_threshold,
            target_price=cfg.target_price, bids=bids, asks=asks,
            timestamp=event_time,
        )

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
                flow = trade_tracker.snapshot(now=event_time)
                profit_lock_reason = net_profit_lock_reason(
                    bid=bid,
                    average_entry=paper.average_entry_price,
                    peak_price=peak,
                    fee_rate=cfg.fee_rate,
                    slippage_bps_per_side=cfg.slippage_bps,
                    momentum_1m_bps=indicator_tracker.return_bps(interval="1m", bars=1),
                    momentum_5m_bps=indicator_tracker.return_bps(interval="5m", bars=1),
                    trade_flow={
                        "ready": flow.ready,
                        "age_seconds": flow.age_seconds,
                        "delta_ratio": flow.delta_ratio,
                    },
                    # L2 replay currently has no event-time wall persistence model;
                    # do not fabricate a book-flow confirmation from one snapshot.
                    book_flow=None,
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

    snap = paper.snapshot(last_bid)
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
        "kline_events": result.kline_events,
        "profit_lock_exits": result.profit_lock_exits,
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
        "notes": result.notes,
    }
