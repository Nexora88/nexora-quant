"""Drawdown circuit breaker: stop fee-bleed overtrading after consecutive losses."""
from __future__ import annotations

from dataclasses import dataclass
import time


@dataclass(slots=True)
class BreakerState:
    consecutive_losses: int
    elevated_min_score: float
    sleep_until: float
    sleeping: bool
    note: str

    def to_dict(self) -> dict:
        return {
            "consecutive_losses": self.consecutive_losses,
            "elevated_min_score": self.elevated_min_score,
            "sleep_until": self.sleep_until,
            "sleeping": self.sleeping,
            "note": self.note,
        }


class DrawdownCircuitBreaker:
    def __init__(
        self,
        *,
        loss_streak: int = 3,
        base_min_score: float = 0.55,
        elevated_min_score: float = 0.75,
        sleep_seconds: float = 900.0,
    ) -> None:
        self.loss_streak = max(2, int(loss_streak))
        self.base_min_score = float(base_min_score)
        self.elevated_min_score = float(elevated_min_score)
        self.sleep_seconds = max(60.0, float(sleep_seconds))
        self._losses = 0
        self._sleep_until = 0.0

    def record_closed_pnl(self, pnl_usdt: float) -> None:
        if pnl_usdt < 0:
            self._losses += 1
            if self._losses >= self.loss_streak:
                self._sleep_until = time.time() + self.sleep_seconds
        else:
            self._losses = 0
            if time.time() >= self._sleep_until:
                self._sleep_until = 0.0

    def effective_min_score(self, base: float | None = None) -> float:
        b = float(base if base is not None else self.base_min_score)
        if self._losses >= self.loss_streak - 1 or time.time() < self._sleep_until:
            return max(b, self.elevated_min_score)
        return b

    def allow_entry(self) -> bool:
        return time.time() >= self._sleep_until

    def snapshot(self) -> BreakerState:
        now = time.time()
        sleeping = now < self._sleep_until
        note = "ok"
        if sleeping:
            note = f"sleep_{int(self._sleep_until - now)}s"
        elif self._losses >= self.loss_streak - 1:
            note = f"elevated_score losses={self._losses}"
        return BreakerState(
            consecutive_losses=self._losses,
            elevated_min_score=self.effective_min_score(),
            sleep_until=self._sleep_until,
            sleeping=sleeping,
            note=note,
        )
