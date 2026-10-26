"""Online market adaptation from recent fills (rolling window)."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class LearnerSnapshot:
    trades: int
    wins: int
    win_rate: float
    avg_pnl: float
    entry_min_score: float
    size_bias: float
    prefer_regime: str
    note: str
    updated_at: str


class OnlineLearner:
    def __init__(
        self,
        *,
        window: int = 30,
        base_entry_min: float = 0.35,
        min_entry: float = 0.25,
        max_entry: float = 0.70,
    ) -> None:
        self.window = window
        self.base_entry_min = base_entry_min
        self.min_entry = min_entry
        self.max_entry = max_entry
        self._pnls: deque[float] = deque(maxlen=window)
        self._regimes: deque[str] = deque(maxlen=window)
        self._entry_min = base_entry_min
        self._size_bias = 1.0
        self._prefer = "any"
        self._note = "cold_start"

    def record_trade(self, pnl_usdt: float, *, regime: str = "unknown") -> None:
        self._pnls.append(float(pnl_usdt))
        self._regimes.append(str(regime or "unknown"))
        self._recompute()

    def _recompute(self) -> None:
        n = len(self._pnls)
        if n < 3:
            self._note = f"warming n={n}"
            return
        wins = sum(1 for x in self._pnls if x > 0)
        wr = wins / n
        avg = sum(self._pnls) / n
        if wr < 0.40:
            self._entry_min = min(self.max_entry, self._entry_min + 0.03)
            self._size_bias = max(0.5, self._size_bias - 0.08)
            self._note = f"defensive wr={wr:.2f} avg={avg:.3f}"
        elif wr > 0.55 and avg > 0:
            self._entry_min = max(self.min_entry, self._entry_min - 0.02)
            self._size_bias = min(1.4, self._size_bias + 0.05)
            self._note = f"aggressive wr={wr:.2f} avg={avg:.3f}"
        else:
            self._entry_min = 0.7 * self._entry_min + 0.3 * self.base_entry_min
            self._size_bias = 0.8 * self._size_bias + 0.2 * 1.0
            self._note = f"neutral wr={wr:.2f} avg={avg:.3f}"
        by: dict[str, float] = {}
        for p, r in zip(self._pnls, self._regimes):
            by[r] = by.get(r, 0.0) + p
        if by:
            best = max(by.items(), key=lambda kv: kv[1])
            if best[1] > 0 and best[0] not in ("unknown", "stressed"):
                self._prefer = best[0]
            else:
                self._prefer = "any"

    @property
    def entry_min_score(self) -> float:
        return float(self._entry_min)

    @property
    def size_bias(self) -> float:
        return float(self._size_bias)

    @property
    def prefer_regime(self) -> str:
        return self._prefer

    def allows_regime(self, regime: str) -> bool:
        if self._prefer == "any":
            return True
        if regime == "stressed":
            return False
        return regime == self._prefer or regime == "unknown"

    def snapshot(self) -> LearnerSnapshot:
        n = len(self._pnls)
        wins = sum(1 for x in self._pnls if x > 0)
        avg = (sum(self._pnls) / n) if n else 0.0
        return LearnerSnapshot(
            trades=n,
            wins=wins,
            win_rate=(wins / n) if n else 0.0,
            avg_pnl=avg,
            entry_min_score=self._entry_min,
            size_bias=self._size_bias,
            prefer_regime=self._prefer,
            note=self._note,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_dict(self) -> dict[str, Any]:
        return self.snapshot().__dict__
