"""Read-only research metrics derived from a synchronized local L2 depth book."""
from __future__ import annotations

from app.depth_book import DepthBook


def depth_imbalance(book: DepthBook, levels: int = 10) -> float | None:
    """Return (bid_qty - ask_qty)/(bid_qty + ask_qty) across best N levels.

    Returns None for an unsynchronized/empty book. This is a descriptive feature,
    not a trading recommendation or a claim that visible liquidity will persist.
    """
    if levels < 1:
        raise ValueError("levels must be >= 1")
    if not book.synchronized or not book.bids or not book.asks:
        return None
    bid_qty = sum(q for _, q in sorted(book.bids.items(), reverse=True)[:levels])
    ask_qty = sum(q for _, q in sorted(book.asks.items())[:levels])
    total = bid_qty + ask_qty
    return (bid_qty - ask_qty) / total if total > 0 else None


def liquidity_walls(
    book: DepthBook, *, levels: int = 20, multiple: float = 3.0
) -> dict[str, list[dict[str, float]]] | None:
    """Flag unusually large visible levels relative to each side's median quantity.

    The result is a heuristic for research only; visible orders may be cancelled
    and are not evidence of executable liquidity at the time an order arrives.
    """
    if levels < 1:
        raise ValueError("levels must be >= 1")
    if multiple <= 1:
        raise ValueError("multiple must be > 1")
    if not book.synchronized or not book.bids or not book.asks:
        return None

    def find(side: dict[float, float], reverse: bool) -> list[dict[str, float]]:
        rows = sorted(side.items(), reverse=reverse)[:levels]
        quantities = sorted(qty for _, qty in rows if qty > 0)
        if not quantities:
            return []
        middle = len(quantities) // 2
        median = (
            quantities[middle] if len(quantities) % 2
            else (quantities[middle - 1] + quantities[middle]) / 2
        )
        if median <= 0:
            return []
        return [
            {"price": price, "quantity": quantity, "multiple_of_median": quantity / median}
            for price, quantity in rows if quantity >= median * multiple
        ]

    return {
        "bids": find(book.bids, True),
        "asks": find(book.asks, False),
    }
