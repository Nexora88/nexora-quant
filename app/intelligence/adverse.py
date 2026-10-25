"""Adverse-selection filter: skip entries when book looks toxic."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(slots=True)
class AdverseVerdict:
    toxic: bool
    reasons: list[str]


class AdverseSelectionFilter:
    def __init__(self, window: int = 40) -> None:
        self._spreads: deque[float] = deque(maxlen=window)
        self._mids: deque[float] = deque(maxlen=window)
        self._micros: deque[float] = deque(maxlen=window)

    def update(self, *, mid: float, spread_bps: float, micro_price: float | None) -> None:
        if mid > 0:
            self._mids.append(mid)
        if spread_bps >= 0:
            self._spreads.append(spread_bps)
        if micro_price is not None and micro_price > 0:
            self._micros.append(micro_price)

    def check(self, *, intend_long: bool) -> AdverseVerdict:
        reasons: list[str] = []
        if len(self._spreads) >= 10:
            avg = sum(self._spreads) / len(self._spreads)
            last = self._spreads[-1]
            if avg > 0 and last > avg * 1.8 and last > 8:
                reasons.append(f"spread_spike {last:.1f}>{avg:.1f}")
        if len(self._mids) >= 8:
            ret = (self._mids[-1] / self._mids[-8] - 1.0) * 10_000
            if intend_long and ret > 12:
                reasons.append(f"late_long move={ret:.1f}bps")
            if not intend_long and ret < -12:
                reasons.append(f"late_short move={ret:.1f}bps")
        if len(self._micros) >= 3 and len(self._mids) >= 1:
            micro = self._micros[-1]
            mid = self._mids[-1]
            prem = (micro / mid - 1.0) * 10_000 if mid > 0 else 0.0
            if intend_long and prem < -3:
                reasons.append(f"micro_against_long {prem:.1f}bps")
            if not intend_long and prem > 3:
                reasons.append(f"micro_against_short {prem:.1f}bps")
        return AdverseVerdict(bool(reasons), reasons)
