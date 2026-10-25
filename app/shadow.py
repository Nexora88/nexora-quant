"""Shadow strategies: parallel paper paths on the same live L2 stream.

Compares Sharpe-like scores offline so operators can promote parameter sets.
Does not place real orders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Any


@dataclass
class ShadowStrategy:
    name: str
    entry_min_score: float
    imbalance_threshold: float
    cash: float = 1000.0
    base_qty: float = 0.0
    avg_entry: float = 0.0
    pnls: list[float] = field(default_factory=list)
    trades: int = 0

    def mark_equity(self, bid: float) -> float:
        return self.cash + self.base_qty * bid

    def maybe_enter(self, *, score: float, ask: float, size_usdt: float, fee: float) -> None:
        if self.base_qty > 0 or score < self.entry_min_score or ask <= 0:
            return
        notional = min(size_usdt, self.cash / (1 + fee))
        if notional < 5:
            return
        qty = notional / ask
        cost = notional * (1 + fee)
        if cost > self.cash:
            return
        self.cash -= cost
        self.base_qty += qty
        self.avg_entry = ask
        self.trades += 1

    def maybe_exit(self, *, bid: float, stop_pct: float, tp_pct: float, fee: float) -> None:
        if self.base_qty <= 0 or self.avg_entry <= 0 or bid <= 0:
            return
        move = (bid / self.avg_entry - 1.0) * 100
        if move > -stop_pct and move < tp_pct:
            return
        proceeds = self.base_qty * bid * (1 - fee)
        pnl = proceeds - (self.avg_entry * self.base_qty)
        self.cash += proceeds
        self.pnls.append(pnl)
        self.base_qty = 0.0
        self.avg_entry = 0.0
        self.trades += 1


def sharpe_like(pnls: list[float]) -> float:
    if len(pnls) < 3:
        return 0.0
    mu = sum(pnls) / len(pnls)
    var = sum((p - mu) ** 2 for p in pnls) / max(1, len(pnls) - 1)
    if var <= 1e-18:
        return 0.0
    return mu / sqrt(var)


@dataclass
class ShadowBook:
    strategies: list[ShadowStrategy] = field(default_factory=list)

    @classmethod
    def default_book(cls, starting_cash: float = 1000.0) -> "ShadowBook":
        return cls(
            strategies=[
                ShadowStrategy("shadow_tight", 0.50, 0.65, cash=starting_cash),
                ShadowStrategy("shadow_base", 0.55, 0.70, cash=starting_cash),
                ShadowStrategy("shadow_strict", 0.65, 0.75, cash=starting_cash),
            ]
        )

    def on_tick(
        self,
        *,
        score: float,
        bid: float,
        ask: float,
        size_usdt: float,
        fee: float,
        stop_pct: float,
        tp_pct: float,
    ) -> None:
        for s in self.strategies:
            s.maybe_exit(bid=bid, stop_pct=stop_pct, tp_pct=tp_pct, fee=fee)
            s.maybe_enter(score=score, ask=ask, size_usdt=size_usdt, fee=fee)

    def leaderboard(self, bid: float) -> list[dict[str, Any]]:
        rows = []
        for s in self.strategies:
            rows.append(
                {
                    "name": s.name,
                    "equity": s.mark_equity(bid),
                    "trades": s.trades,
                    "sharpe_like": sharpe_like(s.pnls),
                    "entry_min_score": s.entry_min_score,
                    "imbalance_threshold": s.imbalance_threshold,
                }
            )
        rows.sort(key=lambda r: r["sharpe_like"], reverse=True)
        return rows
