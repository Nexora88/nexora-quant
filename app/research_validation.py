"""Portfolio accounting, walk-forward splits and conservative queue-fill research.

Research-only utilities. They do not submit orders or change live strategy gates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Iterable


@dataclass
class PortfolioLedger:
    """One shared cash balance and marked positions across all symbols."""

    starting_cash: float
    fee_rate: float = 0.001
    max_positions: int = 3
    cash: float = field(init=False)
    positions: dict[str, dict[str, float]] = field(default_factory=dict)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    realized_pnl: float = 0.0
    fees_paid: float = 0.0

    def __post_init__(self) -> None:
        if not isfinite(self.starting_cash) or self.starting_cash <= 0:
            raise ValueError("starting_cash must be finite and positive")
        if not 0 <= self.fee_rate < 0.1 or self.max_positions < 1:
            raise ValueError("invalid fee rate or max_positions")
        self.cash = self.starting_cash

    def buy(self, symbol: str, quantity: float, price: float) -> bool:
        symbol = symbol.lower()
        if not symbol or not all(isfinite(x) and x > 0 for x in (quantity, price)):
            raise ValueError("symbol, quantity and price must be valid")
        if symbol not in self.positions and len(self.positions) >= self.max_positions:
            return False
        notional = quantity * price
        fee = notional * self.fee_rate
        if notional + fee > self.cash + 1e-9:
            return False
        old = self.positions.get(symbol, {"quantity": 0.0, "cost": 0.0})
        self.positions[symbol] = {
            "quantity": old["quantity"] + quantity,
            "cost": old["cost"] + notional + fee,
        }
        self.cash -= notional + fee
        self.fees_paid += fee
        return True

    def sell(self, symbol: str, quantity: float, price: float) -> float:
        symbol = symbol.lower()
        if not all(isfinite(x) and x > 0 for x in (quantity, price)):
            raise ValueError("quantity and price must be finite and positive")
        position = self.positions.get(symbol)
        if not position or quantity > position["quantity"] + 1e-9:
            raise ValueError("cannot sell more than the held quantity")
        gross = quantity * price
        fee = gross * self.fee_rate
        allocated_cost = position["cost"] * quantity / position["quantity"]
        net = gross - fee
        pnl = net - allocated_cost
        self.cash += net
        self.realized_pnl += pnl
        self.fees_paid += fee
        remaining = position["quantity"] - quantity
        if remaining <= 1e-9:
            del self.positions[symbol]
        else:
            self.positions[symbol] = {
                "quantity": remaining,
                "cost": position["cost"] - allocated_cost,
            }
        return pnl

    def mark(self, timestamp_ns: int, bids: dict[str, float]) -> float:
        equity = self.cash
        for symbol, position in self.positions.items():
            bid = bids.get(symbol)
            if bid is None or not isfinite(bid) or bid <= 0:
                raise ValueError(f"missing valid bid mark for {symbol}")
            equity += position["quantity"] * bid
        self.equity_curve.append({"timestamp_ns": timestamp_ns, "equity": equity})
        return equity


def portfolio_metrics(
    equity_curve: Iterable[dict[str, Any]],
    realized_pnl: float,
    trade_pnls: Iterable[float],
) -> dict[str, Any]:
    points = list(equity_curve)
    pnls = list(trade_pnls)
    if not points:
        raise ValueError("equity_curve cannot be empty")
    equities = [float(p["equity"]) for p in points]
    if any(not isfinite(x) or x <= 0 for x in equities):
        raise ValueError("equity values must be finite and positive")
    peak = equities[0]
    max_dd = 0.0
    for value in equities:
        peak = max(peak, value)
        max_dd = max(max_dd, (peak - value) / peak)
    return {
        "final_equity": equities[-1],
        "realized_pnl": float(realized_pnl),
        "net_return_pct": (equities[-1] / equities[0] - 1.0) * 100.0,
        "max_drawdown_pct": max_dd * 100.0,
        "closed_trades": len(pnls),
        "expectancy_per_trade": sum(pnls) / len(pnls) if pnls else None,
        "win_rate_pct": sum(x > 0 for x in pnls) / len(pnls) * 100.0 if pnls else None,
        "profit_factor": (
            sum(x for x in pnls if x > 0) / abs(sum(x for x in pnls if x < 0))
            if any(x < 0 for x in pnls)
            else (float("inf") if any(x > 0 for x in pnls) else None)
        ),
    }


def walk_forward_splits(
    timestamps_ns: Iterable[int],
    *,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
    test_fraction: float = 0.20,
    step_fraction: float = 0.20,
) -> list[dict[str, int]]:
    """Generate chronological expanding train / validation / test windows.

    Returned boundaries are indices into the sorted timestamp sequence. No
    random shuffle is performed. Fractions describe each initial window.
    """
    fractions = (train_fraction, validation_fraction, test_fraction)
    if any(not 0 < x < 1 for x in fractions) or abs(sum(fractions) - 1.0) > 1e-9:
        raise ValueError("train, validation and test fractions must sum to one")
    if not 0 < step_fraction < 1:
        raise ValueError("step_fraction must be in (0, 1)")
    ts = sorted(int(x) for x in timestamps_ns)
    n = len(ts)
    train_n = int(n * train_fraction)
    val_n = int(n * validation_fraction)
    test_n = n - train_n - val_n
    if min(train_n, val_n, test_n) < 1:
        raise ValueError("not enough timestamps for three non-empty windows")
    step = max(1, int(n * step_fraction))
    splits = []
    start = 0
    while start + train_n + val_n + test_n <= n:
        train_end = start + train_n
        val_end = train_end + val_n
        test_end = val_end + test_n
        splits.append({
            "train_start": start, "train_end": train_end,
            "validation_start": train_end, "validation_end": val_end,
            "test_start": val_end, "test_end": test_end,
            "train_start_ns": ts[start], "train_end_ns": ts[train_end - 1],
            "validation_start_ns": ts[train_end], "validation_end_ns": ts[val_end - 1],
            "test_start_ns": ts[val_end], "test_end_ns": ts[test_end - 1],
        })
        start += step
    return splits


def simulate_queue_fill(
    *,
    requested_quantity: float,
    displayed_ahead_quantity: float,
    traded_through_quantity: float,
    cancel_ahead_quantity: float = 0.0,
    participation_cap: float = 0.10,
) -> dict[str, float]:
    """Conservative passive-fill estimate from observed queue depletion.

    Only prints and cancellations ahead reduce the queue. At most the configured
    fraction of prints behind the queue is credited as executable fill.
    """
    values = (requested_quantity, displayed_ahead_quantity, traded_through_quantity,
              cancel_ahead_quantity)
    if any(not isfinite(x) or x < 0 for x in values):
        raise ValueError("queue quantities must be finite and non-negative")
    if requested_quantity <= 0 or not 0 < participation_cap <= 1:
        raise ValueError("requested_quantity and participation_cap are invalid")
    remaining_ahead = max(0.0, displayed_ahead_quantity - cancel_ahead_quantity
                          - traded_through_quantity)
    queue_cleared = max(0.0, traded_through_quantity + cancel_ahead_quantity
                        - displayed_ahead_quantity)
    credited = min(requested_quantity, queue_cleared * participation_cap)
    return {
        "remaining_ahead_quantity": remaining_ahead,
        "estimated_fill_quantity": credited,
        "fill_ratio": credited / requested_quantity,
    }
