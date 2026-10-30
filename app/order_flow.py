"""Order-flow accumulation: sustained L2 pressure over 1–3s, not one flash OBI.

Retail cannot win pure ms races against co-located HFT. We require the imbalance
to *persist* for a hold window so the signal is directional accumulation, not a spoof flash.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time


@dataclass(slots=True)
class FlowPressure:
    pressure: float
    samples: int
    hold_seconds: float
    ready: bool
    note: str

    @property
    def bullish(self) -> bool:
        return self.ready and self.pressure > 0

    @property
    def bearish(self) -> bool:
        return self.ready and self.pressure < 0


class OrderFlowAccumulator:
    """Rolling window of OBI / micro-premium; ready only after sustained pressure."""

    def __init__(
        self,
        *,
        hold_seconds: float = 1.8,
        min_samples: int = 7,
        min_abs_pressure: float = 0.14,
    ) -> None:
        self.hold_seconds = max(0.8, min(3.5, float(hold_seconds)))
        self.min_samples = max(4, int(min_samples))
        self.min_abs_pressure = max(0.05, float(min_abs_pressure))
        self._buf: deque[tuple[float, float]] = deque(maxlen=500)

    def reset(self) -> None:
        self._buf.clear()

    def update(self, *, imbalance: float, micro_premium_bps: float = 0.0) -> FlowPressure:
        now = time.time()
        obi = (float(imbalance) - 0.5) * 2.0
        micro = max(-1.0, min(1.0, float(micro_premium_bps) / 8.0))
        signed = 0.72 * obi + 0.28 * micro
        self._buf.append((now, signed))
        cutoff = now - self.hold_seconds * 1.6
        while self._buf and self._buf[0][0] < cutoff:
            self._buf.popleft()
        recent = [(t, p) for t, p in self._buf if t >= now - self.hold_seconds]
        if len(recent) < self.min_samples:
            return FlowPressure(0.0, len(recent), self.hold_seconds, False, "warming")
        avg = sum(p for _, p in recent) / len(recent)
        if abs(avg) < self.min_abs_pressure:
            return FlowPressure(avg, len(recent), self.hold_seconds, False, "weak_flow")
        same = sum(1 for _, p in recent if (p >= 0) == (avg >= 0))
        ratio = same / len(recent)
        ready = ratio >= 0.58 and abs(avg) >= self.min_abs_pressure
        note = f"flow={avg:+.2f} persist={ratio:.0%} n={len(recent)} hold={self.hold_seconds:.1f}s"
        return FlowPressure(avg, len(recent), self.hold_seconds, ready, note)
