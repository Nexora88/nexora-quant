"""Session goal: soft-halt new entries when target equity / price is hit."""
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
    """Soft halt only — open positions still managed to exit rules."""
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


def paper_milestones(
    *,
    equity_usdt: float | None,
    starting_cash_usdt: float = 100.0,
) -> dict[str, float | str | None]:
    """First paper targets: 105 → 110 → 140 (multiples of start)."""
    if equity_usdt is None or starting_cash_usdt <= 0:
        return {"multiple": None, "milestone": "unknown", "gap_to_105": None, "gap_to_140": None}
    mult = float(equity_usdt) / float(starting_cash_usdt)
    if mult >= 1.40:
        ms = "target_140"
    elif mult >= 1.10:
        ms = "paper_110"
    elif mult >= 1.05:
        ms = "paper_105"
    else:
        ms = "building"
    return {
        "multiple": round(mult, 4),
        "milestone": ms,
        "gap_to_105": round(max(0.0, starting_cash_usdt * 1.05 - float(equity_usdt)), 2),
        "gap_to_140": round(max(0.0, starting_cash_usdt * 1.40 - float(equity_usdt)), 2),
    }
