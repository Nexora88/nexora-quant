"""Fail-closed risk and cost primitives for Binance USD-M Futures.

This module is deliberately independent from the Spot executor. It does not
send orders or infer liquidation prices; callers must supply exchange values.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


def _finite_positive(name: str, value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def _finite_nonnegative(name: str, value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return value


@dataclass(frozen=True, slots=True)
class FuturesCostEstimate:
    entry_fee_bps: float
    exit_fee_bps: float
    spread_bps: float
    slippage_bps: float
    funding_bps: float
    total_bps: float


def estimate_usdm_round_trip_cost(
    *,
    entry_fee_rate: float,
    exit_fee_rate: float,
    spread_bps: float,
    entry_slippage_bps: float,
    exit_slippage_bps: float,
    funding_rate_per_event: float,
    expected_funding_events: int,
) -> FuturesCostEstimate:
    """Conservative round-trip cost; funding income is never assumed.

    Fee rates are fractions of notional (0.0005 = 5 bps). Funding uses the
    absolute rate for every expected settlement event so a favorable payment
    cannot make an otherwise marginal entry look safer.
    """
    entry_fee = _finite_nonnegative("entry_fee_rate", entry_fee_rate) * 10_000
    exit_fee = _finite_nonnegative("exit_fee_rate", exit_fee_rate) * 10_000
    spread = _finite_nonnegative("spread_bps", spread_bps)
    entry_slip = _finite_nonnegative("entry_slippage_bps", entry_slippage_bps)
    exit_slip = _finite_nonnegative("exit_slippage_bps", exit_slippage_bps)
    funding_rate = float(funding_rate_per_event)
    if not math.isfinite(funding_rate):
        raise ValueError("funding_rate_per_event must be finite")
    if not isinstance(expected_funding_events, int) or expected_funding_events < 0:
        raise ValueError("expected_funding_events must be a non-negative integer")
    funding = abs(funding_rate) * expected_funding_events * 10_000
    slippage = entry_slip + exit_slip
    total = entry_fee + exit_fee + spread + slippage + funding
    return FuturesCostEstimate(entry_fee, exit_fee, spread, slippage, funding, total)


@dataclass(frozen=True, slots=True)
class FuturesPositionSize:
    notional_usdt: float
    initial_margin_usdt: float
    stop_risk_usdt: float
    leverage: float


def size_usdm_position(
    *,
    equity_usdt: float,
    risk_per_trade_pct: float,
    stop_distance_pct: float,
    leverage: float = 1.0,
    max_leverage: float = 1.0,
    max_margin_fraction: float = 0.25,
    max_notional_usdt: float | None = None,
) -> FuturesPositionSize:
    """Size from stop risk, then cap margin and leverage; default is 1x only."""
    equity = _finite_positive("equity_usdt", equity_usdt)
    risk_pct = _finite_positive("risk_per_trade_pct", risk_per_trade_pct)
    stop_pct = _finite_positive("stop_distance_pct", stop_distance_pct)
    lev = _finite_positive("leverage", leverage)
    lev_cap = _finite_positive("max_leverage", max_leverage)
    margin_fraction = _finite_positive("max_margin_fraction", max_margin_fraction)
    if risk_pct > 5.0:
        raise ValueError("risk_per_trade_pct cannot exceed 5%")
    if lev > lev_cap:
        raise ValueError("requested leverage exceeds configured cap")
    if margin_fraction > 1.0:
        raise ValueError("max_margin_fraction cannot exceed 1.0")
    risk_budget = equity * risk_pct / 100.0
    risk_limited_notional = risk_budget / (stop_pct / 100.0)
    margin_limited_notional = equity * margin_fraction * lev
    notional = min(risk_limited_notional, margin_limited_notional)
    if max_notional_usdt is not None:
        cap = _finite_positive("max_notional_usdt", max_notional_usdt)
        notional = min(notional, cap)
    margin = notional / lev
    stop_risk = notional * stop_pct / 100.0
    return FuturesPositionSize(notional, margin, stop_risk, lev)


@dataclass(frozen=True, slots=True)
class LiquidationBuffer:
    safe: bool
    distance_bps: float
    reason: str


def check_liquidation_buffer(
    *,
    side: str,
    mark_price: float,
    liquidation_price: float | None,
    stop_price: float,
    min_buffer_bps: float = 500.0,
) -> LiquidationBuffer:
    """Require an exchange-reported liquidation price beyond the protective stop.

    A missing or geometrically inconsistent liquidation price fails closed.
    Long: liquidation < stop < mark. Short: mark < stop < liquidation.
    """
    side = side.strip().lower()
    if side not in {"long", "short"}:
        raise ValueError("side must be 'long' or 'short'")
    mark = _finite_positive("mark_price", mark_price)
    stop = _finite_positive("stop_price", stop_price)
    buffer = _finite_nonnegative("min_buffer_bps", min_buffer_bps)
    if liquidation_price is None:
        return LiquidationBuffer(False, 0.0, "liquidation_price_missing")
    liq = _finite_positive("liquidation_price", liquidation_price)
    if side == "long":
        if not liq < stop < mark:
            return LiquidationBuffer(False, 0.0, "invalid_long_liquidation_geometry")
        distance = (stop - liq) / mark * 10_000
    else:
        if not mark < stop < liq:
            return LiquidationBuffer(False, 0.0, "invalid_short_liquidation_geometry")
        distance = (liq - stop) / mark * 10_000
    safe = distance >= buffer
    return LiquidationBuffer(
        safe,
        distance,
        "liquidation_buffer_ok" if safe else "liquidation_buffer_too_small",
    )



def passes_futures_cost_gate(
    *,
    gross_expected_move_bps: float,
    costs: FuturesCostEstimate,
    min_cost_multiple: float = 2.0,
) -> bool:
    """Fail-closed Futures entry gate using the same gross-move / total-cost ratio."""
    gross = _finite_nonnegative("gross_expected_move_bps", gross_expected_move_bps)
    multiple = _finite_positive("min_cost_multiple", min_cost_multiple)
    if multiple < 2.0:
        raise ValueError("Futures min_cost_multiple must be >= 2.0")
    total = _finite_positive("total_futures_cost_bps", costs.total_bps)
    return gross > 0.0 and gross >= total * multiple
