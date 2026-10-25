"""Whale / large-player footprint from multi-level L2.

Detects persistent large resting size (liquidity walls) and sudden size
appearance that often precedes institutional flow. Research heuristic only.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Sequence


@dataclass(slots=True)
class WhaleSignal:
    side: str
    strength: float
    size_usdt: float
    note: str


class WhaleTracker:
    def __init__(self, *, multiple: float = 4.0, persist_ticks: int = 5) -> None:
        self.multiple = multiple
        self.persist_ticks = persist_ticks
        self._bid_hits = 0
        self._ask_hits = 0
        self._last_bid_wall = 0.0
        self._last_ask_wall = 0.0
        self._mid_hist: deque[float] = deque(maxlen=60)

    def update(
        self,
        bids: Sequence[tuple[float, float]],
        asks: Sequence[tuple[float, float]],
        mid: float,
    ) -> WhaleSignal:
        if mid > 0:
            self._mid_hist.append(mid)
        if not bids or not asks:
            return WhaleSignal("none", 0.0, 0.0, "empty_book")

        bid_sizes = [p * q for p, q in bids[:10] if q > 0]
        ask_sizes = [p * q for p, q in asks[:10] if q > 0]
        if not bid_sizes or not ask_sizes:
            return WhaleSignal("none", 0.0, 0.0, "empty_sizes")

        med_b = sorted(bid_sizes)[len(bid_sizes) // 2]
        med_a = sorted(ask_sizes)[len(ask_sizes) // 2]
        max_b = max(bid_sizes)
        max_a = max(ask_sizes)

        bid_wall = max_b >= med_b * self.multiple and max_b > 500
        ask_wall = max_a >= med_a * self.multiple and max_a > 500

        self._bid_hits = self._bid_hits + 1 if bid_wall else 0
        self._ask_hits = self._ask_hits + 1 if ask_wall else 0
        if bid_wall:
            self._last_bid_wall = max_b
        if ask_wall:
            self._last_ask_wall = max_a

        if self._bid_hits >= self.persist_ticks and self._bid_hits >= self._ask_hits:
            s = min(1.0, self._bid_hits / 10.0)
            return WhaleSignal("bid", s, self._last_bid_wall, f"bid_wall_usdt={self._last_bid_wall:.0f} persist={self._bid_hits}")
        if self._ask_hits >= self.persist_ticks:
            s = min(1.0, self._ask_hits / 10.0)
            return WhaleSignal("ask", s, self._last_ask_wall, f"ask_wall_usdt={self._last_ask_wall:.0f} persist={self._ask_hits}")
        return WhaleSignal("none", 0.0, 0.0, "no_persistent_wall")
