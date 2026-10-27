"""Dynamic position sizing via fractional Kelly criterion.

f* = (p*b - (1-p)) / b  clamped to [0, max_fraction].
Uses recent trade outcomes when available; otherwise falls back to config caps.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KellyDecision:
    fraction: float
    notional_usdt: float
    win_rate: float
    payoff_ratio: float
    reason: str


class DynamicKellyGate:
    def __init__(
        self,
        *,
        max_fraction: float = 0.25,
        min_order_usdt: float = 5.0,
        max_order_usdt: float = 50.0,
        default_win_rate: float = 0.52,
        default_payoff: float = 1.1,
        window: int = 40,
    ) -> None:
        if not 0 < max_fraction <= 1:
            raise ValueError("max_fraction must be in (0, 1]")
        self.max_fraction = max_fraction
        self.min_order_usdt = min_order_usdt
        self.max_order_usdt = max_order_usdt
        self.default_win_rate = default_win_rate
        self.default_payoff = default_payoff
        self._pnls: deque[float] = deque(maxlen=window)

    def record_pnl(self, pnl_usdt: float) -> None:
        self._pnls.append(float(pnl_usdt))

    def _stats(self) -> tuple[float, float]:
        if len(self._pnls) < 8:
            return self.default_win_rate, self.default_payoff
        wins = [p for p in self._pnls if p > 0]
        losses = [abs(p) for p in self._pnls if p < 0]
        p = len(wins) / len(self._pnls)
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 1.0
        b = (avg_win / avg_loss) if avg_loss > 1e-12 else self.default_payoff
        return max(0.01, min(0.99, p)), max(0.05, b)

    def size(
        self,
        *,
        free_usdt: float,
        fee_rate: float = 0.001,
        size_scale: float = 1.0,
    ) -> KellyDecision:
        """Kelly fraction, optionally scaled by autonomous vol/regime policy (size_scale)."""
        if free_usdt <= 0:
            return KellyDecision(0.0, 0.0, 0.0, 0.0, "No free cash")
        p, b = self._stats()
        f_star = (p * b - (1.0 - p)) / b
        f_star = max(0.0, min(self.max_fraction, f_star))
        f = f_star * 0.5 * max(0.0, min(1.5, float(size_scale)))
        notional = free_usdt * f / (1.0 + fee_rate)
        notional = min(self.max_order_usdt, notional)
        if notional < self.min_order_usdt:
            return KellyDecision(f, 0.0, p, b, "Kelly size below minimum")
        return KellyDecision(
            f,
            round(notional, 8),
            p,
            b,
            f"half_kelly p={p:.2f} b={b:.2f} f*={f_star:.3f} scale={size_scale:.2f}",
        )
