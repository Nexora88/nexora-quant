"""Deterministic execution friction + square-root market impact for paper research."""
from __future__ import annotations

from dataclasses import dataclass
import math
import random


@dataclass(frozen=True, slots=True)
class SimulatedFill:
    requested_quantity: float
    filled_quantity: float
    fill_price: float
    slippage_bps: float
    latency_ms: int
    complete: bool
    impact_bps: float = 0.0


def market_impact_bps(
    *,
    notional_usdt: float,
    visible_liquidity_usdt: float,
    coefficient: float = 0.1,
) -> float:
    """Almgren-style square-root temporary impact in basis points."""
    if notional_usdt <= 0 or visible_liquidity_usdt <= 0 or coefficient < 0:
        return 0.0
    participation = notional_usdt / visible_liquidity_usdt
    return coefficient * math.sqrt(participation) * 100.0


class ExecutionSimulator:
    """Simulate adverse slippage, latency, partial fills, and size-dependent impact."""

    def __init__(
        self,
        *,
        slippage_bps: float = 2.0,
        latency_ms: int = 100,
        partial_fill_probability: float = 0.0,
        seed: int = 0,
        impact_coefficient: float = 0.1,
        default_visible_liquidity_usdt: float = 50_000.0,
    ) -> None:
        if slippage_bps < 0 or latency_ms < 0:
            raise ValueError("slippage and latency cannot be negative")
        if not 0 <= partial_fill_probability <= 1:
            raise ValueError("partial_fill_probability must be in [0, 1]")
        if impact_coefficient < 0:
            raise ValueError("impact_coefficient cannot be negative")
        self.slippage_bps = slippage_bps
        self.latency_ms = latency_ms
        self.partial_fill_probability = partial_fill_probability
        self.impact_coefficient = impact_coefficient
        self.default_visible_liquidity_usdt = default_visible_liquidity_usdt
        self._random = random.Random(seed)

    def fill(
        self,
        *,
        side: str,
        reference_price: float,
        quantity: float,
        visible_liquidity_usdt: float | None = None,
    ) -> SimulatedFill:
        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        if reference_price <= 0 or quantity <= 0:
            raise ValueError("reference_price and quantity must be positive")
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
        notional = quantity * reference_price
        vis = (
            visible_liquidity_usdt
            if visible_liquidity_usdt and visible_liquidity_usdt > 0
            else self.default_visible_liquidity_usdt
        )
        impact = market_impact_bps(
            notional_usdt=notional,
            visible_liquidity_usdt=vis,
            coefficient=self.impact_coefficient,
        )
        slip = base_slip + impact
        direction = 1 if side == "buy" else -1
        price = reference_price * (1 + direction * slip / 10_000)
        filled = quantity
        if self._random.random() < self.partial_fill_probability:
            filled *= self._random.uniform(0.1, 0.9)
        return SimulatedFill(
            requested_quantity=quantity,
            filled_quantity=filled,
            fill_price=price,
            slippage_bps=slip,
            latency_ms=latency,
            complete=filled >= quantity * 0.999,
            impact_bps=impact,
        )

    def fills(self, *, side: str, reference_price: float, quantity: float, **kwargs) -> SimulatedFill:
        """Alias for fill() kept for engine call sites."""
        return getattr(self, "fill")(side=side, reference_price=reference_price, quantity=quantity, **kwargs)
