"""Liquidity wall / iceberg persistence heuristics on L2 depth.

Visible size spikes that survive multiple updates are more informative than
fleeting spoof quotes. Still not executable liquidity guarantees.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Sequence


@dataclass(slots=True)
class WallHit:
    side: str
    price: float
    quantity: float
    multiple_of_median: float
    persistence: int


class WallTracker:
    def __init__(self, *, levels: int = 15, multiple: float = 3.0, history: int = 30) -> None:
        self.levels = levels
        self.multiple = multiple
        self._persist: dict[tuple[str, float], int] = defaultdict(int)
        self._recent: deque[list[WallHit]] = deque(maxlen=history)

    def _median(self, qtys: list[float]) -> float:
        if not qtys:
            return 0.0
        s = sorted(qtys)
        m = len(s) // 2
        return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2

    def update(
        self,
        bids: Sequence[tuple[float, float]],
        asks: Sequence[tuple[float, float]],
    ) -> list[WallHit]:
        hits: list[WallHit] = []
        seen: set[tuple[str, float]] = set()
        for side, rows in (("bid", list(bids)[: self.levels]), ("ask", list(asks)[: self.levels])):
            qtys = [q for _, q in rows if q > 0]
            med = self._median(qtys)
            if med <= 0:
                continue
            for price, qty in rows:
                if qty < med * self.multiple:
                    continue
                key = (side, round(float(price), 8))
                seen.add(key)
                self._persist[key] += 1
                hits.append(
                    WallHit(
                        side=side,
                        price=float(price),
                        quantity=float(qty),
                        multiple_of_median=float(qty / med),
                        persistence=self._persist[key],
                    )
                )
        for key in list(self._persist.keys()):
            if key not in seen:
                self._persist[key] = max(0, self._persist[key] - 1)
                if self._persist[key] == 0:
                    del self._persist[key]
        self._recent.append(hits)
        return hits

    def bias(self) -> float:
        if not self._recent:
            return 0.0
        score = 0.0
        for hits in self._recent:
            for h in hits:
                w = min(3.0, h.persistence / 3.0) * min(5.0, h.multiple_of_median) / 5.0
                score += w if h.side == "bid" else -w
        n = max(1, len(self._recent))
        return max(-1.0, min(1.0, score / n / 3.0))
