"""Session goal: run until target price and/or target equity hit."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class GoalStatus:
    price_hit: bool
    equity_hit: bool
    halt_entries: bool
    note: str


def evaluate_goal(
    *,
    bid: float | None,
    equity_usdt: float | None,
    target_price: float | None,
    target_equity_usdt: float | None,
) -> GoalStatus:
    price_hit = bool(target_price and target_price > 0 and bid and bid >= target_price)
    equity_hit = bool(
        target_equity_usdt
        and target_equity_usdt > 0
        and equity_usdt is not None
        and equity_usdt >= target_equity_usdt
    )
    halt = price_hit or equity_hit
    if price_hit and equity_hit:
        note = "goal_price_and_equity"
    elif price_hit:
        note = "goal_target_price"
    elif equity_hit:
        note = "goal_target_equity"
    else:
        note = "running"
    return GoalStatus(price_hit, equity_hit, halt, note)
