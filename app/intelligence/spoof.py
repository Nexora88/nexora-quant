"""Order-book level persistence filter (anti-spoof heuristic).

Tracks resting size at discrete price levels. Levels that appear and vanish
within ``min_persist_ms`` are treated as transient (possible spoof) and are
down-weighted or excluded from imbalance / wall signals.

Not a perfect spoof detector — only a retail-grade time filter on visible L2.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence


@dataclass(slots=True)
class SpoofReport:
    transient_bid_usdt: float
    transient_ask_usdt: float
    stable_bid_usdt: float
    stable_ask_usdt: float
    spoof_score: float  # 0..1 higher = more transient mass near TOB
    note: str


class OrderPersistenceFilter:
    """Require levels to survive min_persist_ms before counting as real liquidity."""

    def __init__(self, *, min_persist_ms: float = 1000.0, price_tick: float = 0.01) -> None:
        if min_persist_ms < 0:
            raise ValueError("min_persist_ms cannot be negative")
        self.min_persist_ms = min_persist_ms
        self.price_tick = max(price_tick, 1e-12)
        self._bid_levels: dict[float, tuple[float, float]] = {}
        self._ask_levels: dict[float, tuple[float, float]] = {}

    def _key(self, price: float) -> float:
        return round(price / self.price_tick) * self.price_tick

    def update(
        self,
        bids: Sequence[tuple[float, float]],
        asks: Sequence[tuple[float, float]],
        *,
        now_ms: float | None = None,
    ) -> SpoofReport:
        now = now_ms if now_ms is not None else time.time() * 1000.0
        seen_b: set[float] = set()
        seen_a: set[float] = set()

        for px, qty in bids[:20]:
            if px <= 0 or qty <= 0:
                continue
            k = self._key(float(px))
            seen_b.add(k)
            prev = self._bid_levels.get(k)
            if prev is None:
                self._bid_levels[k] = (now, float(qty))
            else:
                self._bid_levels[k] = (prev[0], float(qty))

        for px, qty in asks[:20]:
            if px <= 0 or qty <= 0:
                continue
            k = self._key(float(px))
            seen_a.add(k)
            prev = self._ask_levels.get(k)
            if prev is None:
                self._ask_levels[k] = (now, float(qty))
            else:
                self._ask_levels[k] = (prev[0], float(qty))

        for k in list(self._bid_levels):
            if k not in seen_b:
                del self._bid_levels[k]
        for k in list(self._ask_levels):
            if k not in seen_a:
                del self._ask_levels[k]

        t_bid = s_bid = t_ask = s_ask = 0.0
        for k, (first, size) in self._bid_levels.items():
            notional = k * size
            if now - first >= self.min_persist_ms:
                s_bid += notional
            else:
                t_bid += notional
        for k, (first, size) in self._ask_levels.items():
            notional = k * size
            if now - first >= self.min_persist_ms:
                s_ask += notional
            else:
                t_ask += notional

        total = t_bid + t_ask + s_bid + s_ask
        spoof = ((t_bid + t_ask) / total) if total > 0 else 0.0
        note = (
            f"transient={t_bid + t_ask:.0f} stable={s_bid + s_ask:.0f} "
            f"min_ms={self.min_persist_ms:.0f}"
        )
        return SpoofReport(t_bid, t_ask, s_bid, s_ask, min(1.0, spoof), note)

    def is_spoofy(self, report: SpoofReport, *, threshold: float = 0.55) -> bool:
        return report.spoof_score >= threshold
