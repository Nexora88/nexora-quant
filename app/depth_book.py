"""Sequence-aware Binance depth snapshot/diff synchronizer.

The caller must fetch a REST snapshot and pass buffered websocket updates in order.
A gap invalidates the book; fetch a fresh snapshot before accepting more diffs.
"""
from dataclasses import dataclass, field
from math import isfinite
from typing import Iterable


@dataclass(slots=True)
class DepthBook:
    symbol: str | None = None
    last_update_id: int | None = None
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    synchronized: bool = False

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
