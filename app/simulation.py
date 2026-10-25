"""Deterministic, configurable execution-friction model for paper research."""
from dataclasses import dataclass
import random


@dataclass(frozen=True, slots=True)
class SimulatedFill:
    requested_quantity: float
    filled_quantity: float
    fill_price: float
    slippage_bps: float
    latency_ms: int
    complete: bool


class ExecutionSimulator:
    """Simulate adverse slippage, latency, and partial fills; no network calls."""

    def __init__(
        self, *, slippage_bps: float = 2.0, latency_ms: int = 100,
        partial_fill_probability: float = 0.0, seed: int = 0,
    ) -> None:
        if slippage_bps < 0 or latency_ms < 0:
            raise ValueError("slippage and latency cannot be negative")
        if not 0 <= partial_fill_probability <= 1:
            raise ValueError("partial_fill_probability must be in [0, 1]")
        self.slippage_bps = slippage_bps
        self.latency_ms = latency_ms
        self.partial_fill_probability = partial_fill_probability
        self._random = random.Random(seed)

    def fill(self, *, side: str, reference_price: float, quantity: float) -> SimulatedFill:
        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        if reference_price <= 0 or quantity <= 0:
            raise ValueError("reference_price and quantity must be positive")
        latency = max(0, round(self._random.gauss(self.latency_ms, self.latency_ms * 0.1))) if self.latency_ms else 0
        slip = max(0.0, self._random.gauss(self.slippage_bps, self.slippage_bps * 0.2)) if self.slippage_bps else 0.0
        direction = 1 if side == "buy" else -1
        price = reference_price * (1 + direction * slip / 10_000)
        filled = quantity
        if self._random.random() < self.partial_fill_probability:
            filled *= self._random.uniform(0.1, 0.9)
        return SimulatedFill(
            requested_quantity=quantity, filled_quantity=filled, fill_price=price,
            slippage_bps=slip, latency_ms=latency, complete=filled >= quantity,
        )
