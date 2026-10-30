"""Replay captured L2 depth history through the research signal path.

Event-driven (sequential history only) — no future bars. Defaults use
non-zero latency and slippage so expectancy is not artificially inflated.
"""
from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from app.analytics.microstructure import OrnsteinUhlenbeckTracker
from app.analytics.regime import RegimeClassifier
from app.paper import PaperExecutor
from app.simulation import ExecutionSimulator
from app.strategy import PriceWindow, analyze_market, entry_signal_from_analysis, exit_reason


@dataclass
class L2BacktestConfig:
    starting_cash_usdt: float = 1000.0
    fee_rate: float = 0.001
    order_size_usdt: float = 25.0
    entry_min_score: float = 0.55
    signal_confirmations: int = 2
    take_profit_pct: float = 1.20
    stop_loss_pct: float = 0.35
    trailing_stop_pct: float = 0.25
    imbalance_threshold: float = 0.60
    slippage_bps: float = 3.0
    impact_coefficient: float = 0.1
    latency_ms: int = 50
    partial_fill_probability: float = 0.0
    seed: int = 0
    symbol: str = "btcusdt"


@dataclass
class L2BacktestResult:
    trades: int
    wins: int
    total_pnl: float
    fees_paid: float
    ending_equity: float
    notes: list[str]


def summarize_l2_result(result: L2BacktestResult) -> dict[str, Any]:
    wr = (result.wins / result.trades) if result.trades else 0.0
    return {
        "trades": result.trades,
        "wins": result.wins,
        "win_rate": wr,
        "total_pnl": result.total_pnl,
        "fees_paid": result.fees_paid,
        "ending_equity": result.ending_equity,
        "notes": list(result.notes),
    }


def _iter_events(path: Path) -> Iterator[dict[str, Any]]:
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _walk_book(side: str, levels: list, qty: float, impact_bps: float = 0.0):
    remaining = qty
    filled = 0.0
    cost = 0.0
    for row in levels:
        if remaining <= 0:
            break
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        px, q = float(row[0]), float(row[1])
        if px <= 0 or q <= 0:
            continue
        take = min(remaining, q)
        adj = px * (1.0 + impact_bps / 10_000.0) if side == "buy" else px * (1.0 - impact_bps / 10_000.0)
        cost += adj * take
        filled += take
        remaining -= take
    if filled <= 0:
        return 0.0, 0.0
    return cost / filled, filled


def run_l2_backtest(history_path: str | Path, cfg: L2BacktestConfig | None = None) -> L2BacktestResult:
    cfg = cfg or L2BacktestConfig()
    paper = PaperExecutor(cfg.starting_cash_usdt, cfg.fee_rate)
    sim = ExecutionSimulator(
        slippage_bps=cfg.slippage_bps,
        latency_ms=cfg.latency_ms,
        partial_fill_probability=cfg.partial_fill_probability,
        seed=cfg.seed,
        impact_coefficient=cfg.impact_coefficient,
        symbol=cfg.symbol,
    )
    pw = PriceWindow(maxlen=180)
    ou = OrnsteinUhlenbeckTracker(maxlen=300, z_entry=2.0)
    regime = RegimeClassifier()
    trades = 0
    wins = 0
    total_pnl = 0.0
    confirmations = 0
    peak = 0.0
    notes: list[str] = [f"latency_ms={cfg.latency_ms}", f"slip_bps={cfg.slippage_bps}"]

    path = Path(history_path)
    if not path.exists():
        return L2BacktestResult(0, 0, 0.0, 0.0, cfg.starting_cash_usdt, ["missing_history"])

    for ev in _iter_events(path):
        payload = ev.get("payload") or ev
        bb = payload.get("best_bid") or [0, 0]
        ba = payload.get("best_ask") or [0, 0]
        try:
            bid, bq = float(bb[0]), float(bb[1])
            ask, aq = float(ba[0]), float(ba[1])
        except (TypeError, ValueError, IndexError):
            continue
        if bid <= 0 or ask < bid:
            continue
        bids = payload.get("bids") or [[bid, bq]]
        asks = payload.get("asks") or [[ask, aq]]
        analysis = analyze_market(
            bid=bid, ask=ask, bid_qty=bq, ask_qty=aq,
            price_window=pw, imbalance_threshold=cfg.imbalance_threshold,
            bids=bids, asks=asks, ou=ou, regime_classifier=regime,
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
                target_price=None,
            )
            if reason:
                qty = paper.base_quantity
                avg_px, filled = _walk_book("sell", bids or [[bid, qty]], qty)
                if filled <= 0:
                    fill = sim.fills(side="sell", reference_price=bid, quantity=qty)
                    avg_px, filled = fill.fill_price, fill.filled_quantity
                if filled > 0:
                    trade = paper.sell_quantity(quantity=filled, price=avg_px, reason=f"l2_{reason}")
                    if trade:
                        trades += 1
                        pnl = float(trade.get("pnl_usdt", 0))
                        total_pnl += pnl
                        if pnl > 0:
                            wins += 1
                        peak = 0.0
            continue

        signal = entry_signal_from_analysis(analysis, min_score=cfg.entry_min_score)
        if signal:
            confirmations += 1
        else:
            confirmations = 0
        if signal and confirmations >= cfg.signal_confirmations and paper.base_quantity <= 0:
            notional = min(cfg.order_size_usdt, paper.cash_usdt * 0.95)
            if notional > 5:
                qty = notional / ask
                avg_px, filled = _walk_book("buy", asks or [[ask, qty]], qty)
                if filled <= 0:
                    fill = sim.fills(side="buy", reference_price=ask, quantity=qty)
                    avg_px, filled = fill.fill_price, fill.filled_quantity
                notional = filled * avg_px
                if notional > 0:
                    paper.buy(notional_usdt=notional, price=avg_px, reason=f"l2_{signal.reason}")
                    peak = ask

    snap = paper.snapshot()
    equity = float(snap.get("equity_usdt", snap.get("cash_usdt", cfg.starting_cash_usdt)))
    fees = float(snap.get("fees_paid_usdt", 0))
    return L2BacktestResult(trades, wins, total_pnl, fees, equity, notes)
