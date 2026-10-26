"""Trend following — observe, align, ride; do not predict price."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(slots=True)
class TrendState:
    fast_bps: float
    slow_bps: float
    alignment: str
    strength: float
    allow_long: bool
    note: str


class TrendFollower:
    def __init__(self, *, fast: int = 12, slow: int = 48) -> None:
        self.fast_n = fast
        self.slow_n = slow
        self._mids: deque[float] = deque(maxlen=max(slow + 5, 80))

    def push(self, mid: float) -> None:
        if mid > 0:
            self._mids.append(mid)

    def _mom(self, n: int) -> float:
        if len(self._mids) < max(3, n // 2):
            return 0.0
        k = min(n, len(self._mids))
        a, b = self._mids[-k], self._mids[-1]
        if a <= 0:
            return 0.0
        return (b / a - 1.0) * 10_000

    def state(self) -> TrendState:
        f = self._mom(self.fast_n)
        s = self._mom(self.slow_n)
        if f > 4 and s > 2:
            align, allow, note = "up", True, f"trend_up fast={f:.1f} slow={s:.1f}"
        elif f < -4 and s < -2:
            align, allow, note = "down", False, f"trend_down fast={f:.1f} slow={s:.1f}"
        elif abs(f) < 2 and abs(s) < 2:
            align, allow, note = "flat", False, "trend_flat_wait"
        else:
            align, allow, note = "mixed", False, f"trend_mixed fast={f:.1f} slow={s:.1f}"
        strength = min(1.0, (abs(f) + abs(s)) / 40.0)
        return TrendState(f, s, align, strength, allow, note)

    def trail_exit(
        self,
        *,
        bid: float,
        entry: float,
        peak: float,
        base_trail_pct: float,
        take_profit_pct: float,
        learned_tp_scale: float = 1.0,
    ) -> str | None:
        if entry <= 0 or bid <= 0:
            return None
        move = (bid / entry - 1.0) * 100
        tp = take_profit_pct * max(0.5, min(1.5, learned_tp_scale))
        if move >= tp:
            return "take_profit"
        if peak > entry and base_trail_pct > 0:
            trail = base_trail_pct
            if move > tp * 0.5:
                trail = base_trail_pct * 0.7
            floor = peak * (1.0 - trail / 100.0)
            if bid <= floor:
                return "trailing_stop"
        return None
