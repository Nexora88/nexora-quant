"""Time-based signal confirmation: require score to hold across a wall-clock window.

Retail latency cannot win one-tick races; requiring the same directional score for
N consecutive events *and* a minimum duration filters noise and spoof flashes.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass(slots=True)
class SustainedDecision:
    ready: bool
    hold_seconds: float
    consecutive: int
    avg_score: float
    reason: str


class SustainedSignalGate:
    def __init__(
        self,
        *,
        min_confirmations: int = 5,
        min_hold_seconds: float = 2.0,
        min_score: float = 0.55,
    ) -> None:
        self.min_confirmations = max(1, min_confirmations)
        self.min_hold_seconds = max(0.0, min_hold_seconds)
        self.min_score = min_score
        self._scores: deque[tuple[float, float]] = deque(maxlen=200)

    def update(self, score: float) -> SustainedDecision:
        now = time.monotonic()
        if score >= self.min_score:
            self._scores.append((now, score))
        else:
            self._scores.clear()
            return SustainedDecision(False, 0.0, 0, 0.0, "score_below_threshold")
        consecutive = 0
        for ts, sc in reversed(self._scores):
            if sc >= self.min_score:
                consecutive += 1
            else:
                break
        if consecutive < self.min_confirmations:
            return SustainedDecision(
                False, 0.0, consecutive, score, "need_more_confirmations"
            )
        first_ts = self._scores[-consecutive][0]
        hold = now - first_ts
        avg = sum(s for _, s in list(self._scores)[-consecutive:]) / consecutive
        if hold < self.min_hold_seconds:
            return SustainedDecision(
                False, hold, consecutive, avg, "need_more_hold_time"
            )
        return SustainedDecision(True, hold, consecutive, avg, "sustained_ok")
