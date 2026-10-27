"""Depth-aware execution friction for paper-trading research.

This models visible-book walking and adverse costs. It is not a matching-engine,
queue-priority, hidden-liquidity, or exchange-fill simulator.

Stop / panic sells use a higher stress multiplier so thin books (SOL, BNB)
do not understate real stop-loss slippage versus the configured STOP_LOSS_PCT.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Sequence


_SYMBOL_VISIBLE_USDT: dict[str, float] = {
    "btcusdt": 80_000.0,
    "ethusdt": 40_000.0,
    "solusdt": 12_000.0,
    "bnbusdt": 15_000.0,
}


def symbol_visible_liquidity_usdt(symbol: str | None = None) -> float:
    if not symbol:
        return 50_000.0
    return _SYMBOL_VISIBLE_USDT.get(symbol.lower(), 20_000.0)


@dataclass(frozen=True, slots=True)
class SimulatedFill:
    requested_quantity: float
    filled_quantity: float
    fill_price: float
    slippage_bps: float
    latency_ms: int
    complete: bool
    impact_bps: float = 0.0
    stress_applied: bool = False


def market_impact_bps(
    *,
    notional_usdt: float,
    visible_liquidity_usdt: float,
    coefficient: float = 0.1,
    linear_coefficient: float = 0.05,
) -> float:
    if notional_usdt <= 0 or visible_liquidity_usdt <= 0:
        return 0.0
    x = notional_usdt / visible_liquidity_usdt
    return (
        max(0.0, coefficient) * math.sqrt(x)
        + max(0.0, linear_coefficient) * x
    ) * 100.0


def liquidity_based_slippage_bps(
    *,
    side: str,
    notional_usdt: float,
    levels: list,
    base_slippage_bps: float = 2.0,
    impact_coefficient: float = 0.1,
) -> float:
    if side not in {"buy", "sell"}:
        raise ValueError("side must be 'buy' or 'sell'")
    if not levels or notional_usdt <= 0:
        return base_slippage_bps
    visible = 0.0
    for row in levels:
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            px, qty = float(row[0]), float(row[1])
            if px > 0 and qty > 0:
                visible += px * qty
    impact = market_impact_bps(
        notional_usdt=notional_usdt,
        visible_liquidity_usdt=max(visible, 1.0),
        coefficient=impact_coefficient,
        linear_coefficient=0.05 if impact_coefficient > 0 else 0.0,
    )
    return base_slippage_bps + impact


def _walk_book(
    *, side: str, quantity: float, levels: Sequence[Sequence[float]]
) -> tuple[float, float, float]:
    remaining = quantity
    filled = 0.0
    notional = 0.0
    visible_notional = 0.0
    for row in levels:
        if len(row) < 2:
            continue
        price, available = float(row[0]), float(row[1])
        if not math.isfinite(price) or not math.isfinite(available) or price <= 0 or available <= 0:
            continue
        take = min(remaining, available)
        filled += take
        notional += take * price
        visible_notional += available * price
        remaining -= take
        if remaining <= 1e-12:
            break
    return filled, (notional / filled if filled > 0 else 0.0), visible_notional


class ExecutionSimulator:
    def __init__(
        self,
        *,
        slippage_bps: float = 2.0,
        latency_ms: int = 100,
        partial_fill_probability: float = 0.0,
        seed: int = 0,
        impact_coefficient: float = 0.1,
        default_visible_liquidity_usdt: float = 50_000.0,
        stop_stress_multiplier: float = 2.5,
        stop_tail_bps: float = 8.0,
        symbol: str | None = None,
    ) -> None:
        if slippage_bps < 0 or latency_ms < 0:
            raise ValueError("slippage and latency cannot be negative")
        if not 0 <= partial_fill_probability <= 1:
            raise ValueError("partial_fill_probability must be in [0, 1]")
        if impact_coefficient < 0 or default_visible_liquidity_usdt <= 0:
            raise ValueError("impact coefficient must be non-negative and default liquidity positive")
        if stop_stress_multiplier < 1.0:
            raise ValueError("stop_stress_multiplier must be >= 1")
        if stop_tail_bps < 0:
            raise ValueError("stop_tail_bps cannot be negative")
        self.slippage_bps = slippage_bps
        self.latency_ms = latency_ms
        self.partial_fill_probability = partial_fill_probability
        self.impact_coefficient = impact_coefficient
        self.symbol = (symbol or "").lower() or None
        if self.symbol and abs(default_visible_liquidity_usdt - 50_000.0) < 1e-9:
            self.default_visible_liquidity_usdt = symbol_visible_liquidity_usdt(self.symbol)
        else:
            self.default_visible_liquidity_usdt = default_visible_liquidity_usdt
        self.stop_stress_multiplier = stop_stress_multiplier
        self.stop_tail_bps = stop_tail_bps
        self._vol_bps = 0.0
        self._random = random.Random(seed)

    def set_volatility_bps(self, vol_bps: float) -> None:
        """Feed recent |momentum| bps so stress sells scale with vol."""
        self._vol_bps = max(0.0, float(vol_bps))

    def effective_stress_multiplier(self) -> float:
        scale = 1.0 + min(0.8, max(0.0, (self._vol_bps - 15.0) / 40.0) * 0.8)
        return self.stop_stress_multiplier * scale

    def fill(
        self,
        *,
        side: str,
        reference_price: float,
        quantity: float,
        visible_liquidity_usdt: float | None = None,
        book_levels: Sequence[Sequence[float]] | None = None,
        stress: bool = False,
    ) -> SimulatedFill:
        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        if (
            not math.isfinite(reference_price)
            or not math.isfinite(quantity)
            or reference_price <= 0
            or quantity <= 0
        ):
            raise ValueError("reference_price and quantity must be finite and positive")

        latency = (
            max(0, round(self._random.gauss(self.latency_ms, self.latency_ms * 0.1)))
            if self.latency_ms
            else 0
        )
        base_slip = (
            max(0.0, self._random.gauss(self.slippage_bps, self.slippage_bps * 0.2))
            if self.slippage_bps
            else 0.0
        )
        requested_notional = quantity * reference_price

        if book_levels is not None:
            book_filled, book_vwap, book_visible = _walk_book(
                side=side, quantity=quantity, levels=book_levels
            )
            filled = book_filled
            visible = max(book_visible, 1.0)
            anchor = book_vwap if book_filled > 0 else reference_price
        else:
            filled = quantity
            visible = (
                visible_liquidity_usdt
                if visible_liquidity_usdt and visible_liquidity_usdt > 0
                else self.default_visible_liquidity_usdt
            )
            anchor = reference_price

        if filled <= 0:
            return SimulatedFill(
                quantity, 0.0, reference_price, base_slip, latency, False, 0.0, False
            )

        if self._random.random() < self.partial_fill_probability:
            filled *= self._random.uniform(0.1, 0.9)

        impact = market_impact_bps(
            notional_usdt=min(requested_notional, filled * anchor),
            visible_liquidity_usdt=visible,
            coefficient=self.impact_coefficient,
            linear_coefficient=0.05 if self.impact_coefficient > 0 else 0.0,
        )
        stress_on = bool(stress and side == "sell")
        if stress_on:
            impact *= self.effective_stress_multiplier()
            tail = self.stop_tail_bps * (1.0 + min(1.0, self._vol_bps / 50.0))
            if tail > 0:
                impact += abs(self._random.gauss(0.0, tail))
        direction = 1 if side == "buy" else -1
        total_slip = base_slip + impact
        fill_price = anchor * (1 + direction * total_slip / 10_000)
        return SimulatedFill(
            requested_quantity=quantity,
            filled_quantity=filled,
            fill_price=fill_price,
            slippage_bps=total_slip,
            latency_ms=latency,
            complete=filled >= quantity * 0.999,
            impact_bps=impact,
            stress_applied=stress_on,
        )

    def fills(
        self, *, side: str, reference_price: float, quantity: float, **kwargs
    ) -> SimulatedFill:
        return self.fill(
            side=side, reference_price=reference_price, quantity=quantity, **kwargs
        )
