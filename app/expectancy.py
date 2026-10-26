"""Expectancy helpers for asymmetric reward/risk sizing policy."""
from __future__ import annotations


def reward_risk_ratio(*, take_profit_pct: float, stop_loss_pct: float) -> float:
    if stop_loss_pct <= 0:
        return float("inf")
    return take_profit_pct / stop_loss_pct


def breakeven_win_rate(
    *,
    take_profit_pct: float,
    stop_loss_pct: float,
    fee_rate: float = 0.001,
) -> float:
    """Minimum win rate (0-1) for zero expectancy after round-trip fees (approx)."""
    tp = take_profit_pct / 100.0
    sl = stop_loss_pct / 100.0
    fee = 2.0 * fee_rate
    denom = tp + sl
    if denom <= 0:
        return 1.0
    return max(0.0, min(1.0, (sl + fee) / denom))


def asymmetric_expectancy(
    *,
    win_rate: float,
    take_profit_pct: float,
    stop_loss_pct: float,
    fee_rate: float = 0.001,
) -> float:
    """Expected return fraction of notional per completed trade (approx)."""
    p = max(0.0, min(1.0, win_rate))
    tp = take_profit_pct / 100.0
    sl = stop_loss_pct / 100.0
    fee = 2.0 * fee_rate
    return p * (tp - fee) - (1.0 - p) * (sl + fee)
