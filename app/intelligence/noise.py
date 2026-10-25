"""Noise filter: reject flicker signals that do not survive brief time."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(slots=True)
class NoiseVerdict:
    noisy: bool
    stability: float
    reason: str


class NoiseFilter:
    def __init__(self, *, window: int = 12, min_stability: float = 0.55) -> None:
        self._scores: deque[float] = deque(maxlen=window)
        self._signs: deque[int] = deque(maxlen=window)
        self.min_stability = min_stability

    def update(self, score: float) -> NoiseVerdict:
        self._scores.append(score)
        self._signs.append(1 if score > 0.15 else -1 if score < -0.15 else 0)
        if len(self._scores) < max(4, self._scores.maxlen // 2):
            return NoiseVerdict(True, 0.0, "warming_up")
        pos = sum(1 for s in self._signs if s > 0)
        neg = sum(1 for s in self._signs if s < 0)
        majority = max(pos, neg)
        stability = majority / len(self._signs)
        mean = sum(self._scores) / len(self._scores)
        var = sum((x - mean) ** 2 for x in self._scores) / len(self._scores)
        if stability < self.min_stability:
            return NoiseVerdict(True, stability, f"unstable_sign={stability:.2f}")
        if var > 0.25:
            return NoiseVerdict(True, stability, f"high_var={var:.3f}")
        return NoiseVerdict(False, stability, f"stable={stability:.2f}")
