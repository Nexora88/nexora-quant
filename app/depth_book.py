"""Sequence-aware Binance depth snapshot/diff synchronizer.

The caller must fetch a REST snapshot and pass buffered websocket updates in order.
A gap invalidates the book; fetch a fresh snapshot before accepting more diffs.
"""
from dataclasses import dataclass, field
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
        self.bids = {float(p): float(q) for p, q in bids if float(q) > 0}
        self.asks = {float(p): float(q) for p, q in asks if float(q) > 0}
        if any(p <= 0 or q < 0 for p, q in [*self.bids.items(), *self.asks.items()]):
            raise ValueError("prices must be positive and quantities non-negative")
        self.last_update_id = last_update_id
        self.synchronized = True

    def apply_diff(
        self, *, first_update_id: int, final_update_id: int,
        bids: Iterable[tuple[float, float]], asks: Iterable[tuple[float, float]],
        previous_final_update_id: int | None = None,
    ) -> bool:
        """Apply a Binance diff event; return True if accepted, False on gap/stale."""
        if not self.synchronized or self.last_update_id is None:
            return False
        if final_update_id <= self.last_update_id:
            return False  # stale or duplicate event
        if previous_final_update_id is not None:
            if first_update_id > self.last_update_id + 1:
                self.synchronized = False
                return False
        elif first_update_id > self.last_update_id + 1:
            self.synchronized = False
            return False

        def _apply(side: dict[float, float], levels: Iterable[tuple[float, float]]) -> None:
            for price, qty in levels:
                p, q = float(price), float(qty)
                if q == 0:
                    side.pop(p, None)
                elif p > 0 and q > 0:
                    side[p] = q

        _apply(self.bids, bids)
        _apply(self.asks, asks)
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
