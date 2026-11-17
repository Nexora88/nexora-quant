"""Fee-aware profit lock with independent reversal confirmations."""
from __future__ import annotations

from math import isfinite


def net_profit_lock_reason(
    *,
    bid: float,
    average_entry: float,
    peak_price: float,
    fee_rate: float,
    slippage_bps_per_side: float,
    momentum_1m_bps: float | None,
    momentum_5m_bps: float | None,
    trade_flow: dict | None,
    book_flow: dict | None,
    giveback_ratio: float = 0.55,
) -> str | None:
    """Return an existing hard-exit reason only when net profit is protected.

    Costs include both-side fees and a conservative two-side slippage estimate.
    Reversal requires two independent groups: multi-timeframe momentum,
    executed aggressor flow, and sustained L2 book pressure.
    """
    values = (bid, average_entry, peak_price, fee_rate, slippage_bps_per_side, giveback_ratio)
    if not all(isfinite(float(v)) for v in values):
        return None
    if bid <= 0 or average_entry <= 0 or peak_price <= 0 or fee_rate < 0 or slippage_bps_per_side < 0:
        return None
    if not 0.1 <= giveback_ratio <= 0.9:
        raise ValueError("giveback_ratio must be between 0.1 and 0.9")

    cost_pct = 2.0 * fee_rate * 100.0 + 2.0 * slippage_bps_per_side / 100.0
    current_net_pct = (bid / average_entry - 1.0) * 100.0 - cost_pct
    peak_net_pct = (peak_price / average_entry - 1.0) * 100.0 - cost_pct
    activation_pct = max(0.25, cost_pct + 0.15)

    if peak_net_pct >= activation_pct:
        locked_floor_pct = max(0.08, peak_net_pct * giveback_ratio)
        if current_net_pct <= locked_floor_pct:
            return "trailing_stop"

    if current_net_pct < max(0.10, cost_pct * 0.35):
        return None

    momentum_bearish = (
        momentum_1m_bps is not None and momentum_1m_bps <= -5.0
        and momentum_5m_bps is not None and momentum_5m_bps < 0.0
    )
    trade_age = trade_flow.get("age_seconds") if trade_flow else None
    trade_bearish = bool(
        trade_flow
        and trade_flow.get("ready") is True
        and trade_age is not None
        and float(trade_age) <= 2.5
        and float(trade_flow.get("delta_ratio") or 0.0) <= -0.10
    )
    book_bearish = bool(
        book_flow
        and book_flow.get("ready") is True
        and float(book_flow.get("pressure") or 0.0) <= -0.10
    )
    if sum((momentum_bearish, trade_bearish, book_bearish)) >= 2:
        return "momentum_reversal"
    return None
