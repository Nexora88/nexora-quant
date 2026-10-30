"""L2 event-driven backtest over MarketHistoryWriter gzip JSONL.

Replays depth snapshots in timestamp order. Fills walk the visible book with
Almgren-style impact — usable for imbalance / wall research that OHLCV cannot do.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.market_history import replay_market_history
from app.paper import PaperExecutor
from app.portfolio import size_from_free_cash
from app.simulation import ExecutionSimulator, market_impact_bps
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
    notes: str = (
        "L2 replay uses recorded visible book only; cancelled liquidity and true "
        "queue position are not recoverable from public depth diffs."
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
    pw = PriceWindow(maxlen=180)
    result = L2BacktestResult()
    confirmations = 0
    peak = 0.0

    for event in replay_market_history(path):
        result.events_seen += 1
        payload = event.get("payload") or event
        ts = int(event.get("timestamp_ns") or payload.get("timestamp_ns") or 0)
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
        if bid <= 0 or ask < bid:
            continue
        bids = payload.get("bids") if isinstance(payload.get("bids"), list) else [[bid, bid_qty]]
        asks = payload.get("asks") if isinstance(payload.get("asks"), list) else [[ask, ask_qty]]
        analysis = analyze_market(
            bid=bid, ask=ask, bid_qty=bid_qty, ask_qty=ask_qty,
            price_window=pw, imbalance_threshold=cfg.imbalance_threshold,
            target_price=cfg.target_price, bids=bids, asks=asks,
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
            if reason:
                qty = paper.base_quantity
                impact = market_impact_bps(
                    notional_usdt=qty * bid,
                    visible_liquidity_usdt=max(bid * bid_qty, 1.0),
                    coefficient=cfg.impact_coefficient,
                )
                avg_px, filled = _walk_book("sell", bids or [[bid, qty]], qty, impact_bps=impact)
                if filled <= 0:
                    fill = sim.fills(side="sell", reference_price=bid, quantity=qty)
                    avg_px, filled = fill.fill_price, fill.filled_quantity
                if filled > 0:
                    trade = paper.sell_quantity(
                        quantity=filled, price=avg_px, reason=f"l2_{reason};impact_bps={impact:.2f}"
                    )
                    if trade:
                        result.trades.append({**trade, "timestamp_ns": ts})
                        result.exits += 1
                        peak = 0.0
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
                impact = market_impact_bps(
                    notional_usdt=sizing.notional_usdt,
                    visible_liquidity_usdt=max(ask * ask_qty, 1.0),
                    coefficient=cfg.impact_coefficient,
                )
                avg_px, filled = _walk_book("buy", asks or [[ask, qty]], qty, impact_bps=impact)
                if filled <= 0:
                    fill = sim.fills(side="buy", reference_price=ask, quantity=qty)
                    avg_px, filled = fill.fill_price, fill.filled_quantity
                notional = filled * avg_px
                if notional > 0:
                    trade = paper.buy(
                        notional_usdt=notional, price=avg_px,
                        reason=f"l2_entry;score={analysis.score:.2f};impact_bps={impact:.2f}",
                    )
                    result.trades.append({**trade, "timestamp_ns": ts})
                    result.entries += 1
                    peak = avg_px
                    confirmations = 0

        snap = paper.snapshot(bid)
        result.equity_curve.append({
            "timestamp_ns": ts, "equity": snap["equity_usdt"],
            "mid": (bid + ask) / 2, "score": analysis.score,
        })

    snap = paper.snapshot()
    result.final_equity = float(snap["equity_usdt"])
    result.final_cash = float(snap["cash_usdt"])
    result.realized_pnl = float(snap["realized_pnl_usdt"])
    result.trade_count = len(result.trades)
    return result


def summarize_l2_result(result: L2BacktestResult) -> dict[str, Any]:
    start = result.equity_curve[0]["equity"] if result.equity_curve else result.final_equity
    ret = (result.final_equity / start - 1.0) if start else 0.0
    return {
        "events_seen": result.events_seen,
        "signals": result.signals,
        "entries": result.entries,
        "exits": result.exits,
        "trade_count": result.trade_count,
        "final_equity": result.final_equity,
        "realized_pnl": result.realized_pnl,
        "return_pct": ret * 100,
        "notes": result.notes,
    }
