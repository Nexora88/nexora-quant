"""Sequence-aware Binance depth snapshot/diff synchronizer.

The caller must fetch a REST snapshot and pass buffered websocket updates in order.
A gap invalidates the book; fetch a fresh snapshot before accepting more diffs.
"""
from dataclasses import dataclass, field
from heapq import nlargest, nsmallest
from operator import itemgetter
from math import isfinite
from types import MappingProxyType
from typing import Iterable, Mapping
import time


@dataclass(frozen=True, slots=True)
class DepthSnapshot:
    """Read-only top levels and source clocks for one published book revision."""

    symbol: str
    last_update_id: int
    bids: Mapping[float, float]
    asks: Mapping[float, float]
    received_at_ns: int
    received_monotonic_ns: int
    exchange_at_ms: int | None = None
    testnet: bool = False

    @property
    def synchronized(self) -> bool:
        return True

    @property
    def best_bid(self) -> tuple[float, float] | None:
        return next(iter(self.bids.items()), None)

    @property
    def best_ask(self) -> tuple[float, float] | None:
        return next(iter(self.asks.items()), None)

    def age_seconds(self) -> float:
        local_age = (time.monotonic_ns() - self.received_monotonic_ns) / 1e9
        # Use ingress clock skew only once; wall-clock jumps after ingress must
        # not make a queued or delayed exchange event appear fresh again.
        source_delay = 0.0
        if self.exchange_at_ms is not None:
            source_delay = (self.received_at_ns - self.exchange_at_ms * 1_000_000) / 1e9
            if source_delay < -5.0:
                return float("inf")
        return max(0.0, local_age) + max(0.0, source_delay)


@dataclass(slots=True)
class DepthBook:
    symbol: str | None = None
    last_update_id: int | None = None
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    synchronized: bool = False

    def publish(
        self, *, received_at_ns: int, received_monotonic_ns: int,
        exchange_at_ms: int | None = None, levels: int = 20, testnet: bool = False,
    ) -> DepthSnapshot:
        if not self.synchronized or self.last_update_id is None or not self.symbol:
            raise ValueError("only synchronized books with a symbol can be published")
        return DepthSnapshot(
            self.symbol, self.last_update_id,
            MappingProxyType(dict(nlargest(levels, self.bids.items(), key=itemgetter(0)))),
            MappingProxyType(dict(nsmallest(levels, self.asks.items(), key=itemgetter(0)))),
            received_at_ns, received_monotonic_ns, exchange_at_ms, testnet,
        )

    def load_snapshot(
        self, *, last_update_id: int,
        bids: Iterable[tuple[float, float]], asks: Iterable[tuple[float, float]],
    ) -> None:
        if last_update_id < 0:
            raise ValueError("last_update_id must be non-negative")

        def validated(levels: Iterable[tuple[float, float]]) -> dict[float, float]:
            result: dict[float, float] = {}
            for price, qty in levels:
                p, q = float(price), float(qty)
                if not isfinite(p) or not isfinite(q) or p <= 0 or q < 0:
                    raise ValueError("depth levels must have finite positive prices and non-negative quantities")
                if q > 0:
                    result[p] = q
            return result

        new_bids = validated(bids)
        new_asks = validated(asks)
        self.bids = new_bids
        self.asks = new_asks
        self.last_update_id = last_update_id
        self.synchronized = True

    def apply_diff(
        self, *, first_update_id: int, final_update_id: int,
        bids: Iterable[tuple[float, float]], asks: Iterable[tuple[float, float]],
    ) -> bool:
        """Apply a Binance diff event; return True if accepted, False on gap/stale."""
        if not self.synchronized or self.last_update_id is None:
            return False
        if first_update_id < 0 or final_update_id < first_update_id:
            self.synchronized = False
            return False
        if final_update_id <= self.last_update_id:
            return False  # stale or duplicate event

        # Binance Spot diff-depth events use U/u ranges; the pu field belongs
        # to USD-M Futures streams and is not present in Spot payloads. For Spot,
        # overlapping ranges are valid; only a forward gap is fatal.
        if first_update_id > self.last_update_id + 1:
            self.synchronized = False
            return False

        def validated(levels: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
            result: list[tuple[float, float]] = []
            for price, qty in levels:
                p, q = float(price), float(qty)
                if not isfinite(p) or not isfinite(q) or p <= 0 or q < 0:
                    self.synchronized = False
                    raise ValueError("depth levels must have finite positive prices and non-negative quantities")
                result.append((p, q))
            return result

        # Validate both sides before mutating either side.
        bid_levels = validated(bids)
        ask_levels = validated(asks)

        def apply(side: dict[float, float], levels: list[tuple[float, float]]) -> None:
            for price, qty in levels:
                if qty == 0:
                    side.pop(price, None)
                else:
                    side[price] = qty

        apply(self.bids, bid_levels)
        apply(self.asks, ask_levels)
        self.last_update_id = final_update_id
        return True

    @property
    def best_bid(self) -> tuple[float, float] | None:
        if not self.bids:
            return None
        p = max(self.bids)
        return p, self.bids[p]

    @property
    def best_ask(self) -> tuple[float, float] | None:
        if not self.asks:
            return None
        p = min(self.asks)
        return p, self.asks[p]
