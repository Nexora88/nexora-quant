"""Dynamic Binance REST weight limiter (token bucket)."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

PATH_WEIGHT: dict[str, int] = {
    "/api/v3/ping": 1,
    "/api/v3/time": 1,
    "/api/v3/ticker/price": 2,
    "/api/v3/exchangeInfo": 20,
    "/api/v3/account": 20,
    "/api/v3/order": 1,
    "/api/v3/openOrders": 6,
    "/api/v3/myTrades": 20,
    "/api/v3/allOrderList": 20,
    "/api/v3/orderList": 4,
}


@dataclass
class RateLimiterStats:
    weight_used_1m: float
    capacity: float
    waits: int
    last_wait_ms: float


class BinanceWeightLimiter:
    def __init__(self, *, capacity: float = 2400.0, refill_per_sec: float | None = None) -> None:
        self.capacity = float(capacity)
        self.refill_per_sec = float(refill_per_sec if refill_per_sec is not None else capacity / 60.0)
        self._tokens = self.capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()
        self._waits = 0
        self._last_wait_ms = 0.0

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        self._last = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_sec)

    def weight_for(self, path: str, method: str = "GET") -> int:
        w = PATH_WEIGHT.get(path, 1)
        if method == "POST" and path == "/api/v3/order":
            return 1
        return max(1, int(w))

    def acquire(self, weight: int = 1, *, max_wait_sec: float = 30.0) -> float:
        need = max(1, int(weight))
        waited = 0.0
        deadline = time.monotonic() + max_wait_sec
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= need:
                    self._tokens -= need
                    if waited > 0:
                        self._waits += 1
                        self._last_wait_ms = waited * 1000.0
                    return waited
                deficit = need - self._tokens
                sleep_s = deficit / max(self.refill_per_sec, 1e-6)
            sleep_s = min(max(sleep_s, 0.01), max(0.0, deadline - time.monotonic()))
            if sleep_s <= 0:
                with self._lock:
                    self._tokens = max(0.0, self._tokens - need)
                    self._waits += 1
                    self._last_wait_ms = waited * 1000.0
                return waited
            time.sleep(sleep_s)
            waited += sleep_s

    def stats(self) -> RateLimiterStats:
        with self._lock:
            self._refill()
            return RateLimiterStats(self.capacity - self._tokens, self.capacity, self._waits, self._last_wait_ms)


_GLOBAL = BinanceWeightLimiter()


def global_limiter() -> BinanceWeightLimiter:
    return _GLOBAL
