"""Risk-capped dynamic sizing helpers for paper trading only."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SizingDecision:
    notional_usdt: float
    reason: str


def size_from_free_cash(
    *,
    free_usdt: float,
    allocation_fraction: float = 0.80,
    fee_rate: float = 0.001,
    max_order_usdt: float = 50.0,
    min_order_usdt: float = 5.0,
) -> SizingDecision:
    """Allocate a fraction of free cash while reserving fees and respecting caps.

    The returned notional excludes fees. This is a research sizing rule, not a
    recommendation to trade or a guarantee of positive returns.
    """
    if free_usdt < 0:
        raise ValueError("free_usdt cannot be negative")
    if not 0 < allocation_fraction <= 1:
        raise ValueError("allocation_fraction must be in (0, 1]")
    if not 0 <= fee_rate < 0.1:
        raise ValueError("fee_rate must be in [0, 0.1)")
    if max_order_usdt <= 0 or min_order_usdt <= 0 or min_order_usdt > max_order_usdt:
        raise ValueError("invalid order size limits")
    spendable = free_usdt * allocation_fraction
    notional = min(max_order_usdt, spendable / (1.0 + fee_rate))
    if notional < min_order_usdt:
        return SizingDecision(0.0, "Below minimum paper order size")
    return SizingDecision(round(notional, 8), "Dynamic free-cash sizing")
