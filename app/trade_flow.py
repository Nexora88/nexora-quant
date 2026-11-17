"""Aggressor-side trade flow metrics from executed Binance Spot trades.

Order-book imbalance and executed trade flow are deliberately separate signals.
A buyer_is_maker trade was initiated by a seller, so its signed volume is negative.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
import time

from app.events import TradeTick


@dataclass(frozen=True, slots=True)
class TradeFlowSnapshot:
    buy_qty: float
    sell_qty: float
    delta_qty: float
    cvd: float
    buy_sell_ratio: float
    delta_ratio: float
    trades: int
    age_seconds: float | None
    ready: bool
    note: str

    @property
    def bullish(self) -> bool:
        return self.ready and self.delta_ratio > 0.05

    @property
    def bearish(self) -> bool:
        return self.ready and self.delta_ratio < -0.05


class TradeFlowTracker:
    """Rolling aggressor volume and CVD with explicit freshness/warm-up gates."""

    def __init__(
        self,
        *,
        window_seconds: float = 10.0,
        min_trades: int = 20,
        max_age_seconds: float = 2.5,
        max_samples: int = 5000,
    ) -> None:
        if window_seconds <= 0 or min_trades < 1 or max_age_seconds <= 0 or max_samples < min_trades:
            raise ValueError("invalid trade-flow configuration")
        self.window_seconds = float(window_seconds)
        self.min_trades = int(min_trades)
        self.max_age_seconds = float(max_age_seconds)
        self._events: deque[tuple[float, float, float]] = deque(maxlen=max_samples)
        self._last_ts = 0.0
        self._cvd = 0.0

    @staticmethod
    def _timestamp(value: datetime | float | None) -> float:
        if value is None:
            return time.time()
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.timestamp()
        return float(value)

    def update(self, trade: TradeTick, *, now: float | None = None) -> TradeFlowSnapshot:
        price = float(trade.price)
        qty = float(trade.quantity)
        ts = self._timestamp(trade.received_at)
        if not isfinite(price) or not isfinite(qty) or price <= 0 or qty <= 0 or not isfinite(ts):
            return self.snapshot(now=now)
        # Ignore duplicate/out-of-order events; never let an old event make the feed look fresh.
        if ts <= self._last_ts:
            return self.snapshot(now=now)
        signed = -qty if trade.buyer_is_maker else qty
        self._events.append((ts, signed, qty))
        self._last_ts = ts
        self._cvd += signed
        return self.snapshot(now=now if now is not None else ts)

    def snapshot(self, *, now: float | None = None) -> TradeFlowSnapshot:
        current = time.time() if now is None else float(now)
        cutoff = current - self.window_seconds
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()
        recent = [row for row in self._events if row[0] <= current]
        buy = sum(qty for _, signed, qty in recent if signed > 0)
        sell = sum(qty for _, signed, qty in recent if signed < 0)
        delta = buy - sell
        total = buy + sell
        ratio = min(1000.0, buy / sell) if sell > 0 else (1000.0 if buy > 0 else 1.0)
        delta_ratio = delta / total if total > 0 else 0.0
        age = max(0.0, current - self._last_ts) if self._last_ts else None
        fresh = age is not None and age <= self.max_age_seconds
        ready = len(recent) >= self.min_trades and fresh and total > 0
        note = (
            f"trade_flow={'ready' if ready else 'warming_or_stale'} "
            f"delta={delta_ratio:+.3f} trades={len(recent)} "
            f"age={age:.2f}s" if age is not None
            else "trade_flow=no_data"
        )
        return TradeFlowSnapshot(
            buy_qty=buy,
            sell_qty=sell,
            delta_qty=delta,
            cvd=self._cvd,
            buy_sell_ratio=ratio,
            delta_ratio=delta_ratio,
            trades=len(recent),
            age_seconds=age,
            ready=ready,
            note=note,
        )

    def reset(self) -> None:
        self._events.clear()
        self._last_ts = 0.0
        self._cvd = 0.0
