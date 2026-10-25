"""Event-time order-book replay helpers for conservative research.

The replay is intentionally deterministic. It applies depth snapshots and explicit
cancel/depletion events in timestamp order, then executes orders after configured
latency against the book visible at execution time. It is not exchange-grade.
"""
from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any, Iterable


def replay_orders(
    events: Iterable[dict[str, Any]],
    orders: Iterable[dict[str, Any]],
    *,
    latency_ns: int = 0,
    fee_rate: float = 0.001,
) -> list[dict[str, Any]]:
    """Replay timestamped depth/cancel events and orders, returning fee-aware fills.

    Event payload for depth: {"bids": [[price, qty], ...], "asks": [...]}
    Event payload for cancel/depletion: {"side": "bid"|"ask", "price": float,
    "quantity": float}; quantity is removed from that level, clamped at zero.
    Order fields: timestamp_ns, side ("buy"|"sell"), quantity.
    Orders execute against the latest book at timestamp_ns + latency_ns.
    """
    if latency_ns < 0 or not 0 <= fee_rate < 0.1:
        raise ValueError("latency_ns must be non-negative and fee_rate in [0, 0.1)")
    timeline = []
    for e in events:
        ts = e.get("timestamp_ns")
        if isinstance(ts, bool) or not isinstance(ts, int) or ts < 0:
            raise ValueError("invalid event timestamp")
        timeline.append((ts, 0, deepcopy(e)))
    for o in orders:
        ts = o.get("timestamp_ns")
        if isinstance(ts, bool) or not isinstance(ts, int) or ts < 0:
            raise ValueError("invalid order timestamp")
        timeline.append((ts + latency_ns, 1, deepcopy(o)))
    timeline.sort(key=lambda item: (item[0], item[1]))
    book: dict[str, dict[float, float]] = {"bid": {}, "ask": {}}
    results: list[dict[str, Any]] = []
    for ts, kind, item in timeline:
        if kind == 0:
            event_type = item.get("event_type")
            payload = item.get("payload", {})
            if not isinstance(payload, dict):
                raise ValueError("event payload must be an object")
            if event_type == "depth":
                for side, key in (("bid", "bids"), ("ask", "asks")):
                    levels = payload.get(key, [])
                    if not isinstance(levels, list):
                        raise ValueError(f"{key} must be a list")
                    updated: dict[float, float] = {}
                    for row in levels:
                        if not isinstance(row, (list, tuple)) or len(row) < 2:
                            raise ValueError("depth level must contain price and quantity")
                        price, qty = float(row[0]), float(row[1])
                        if not isfinite(price) or not isfinite(qty) or price <= 0 or qty < 0:
                            raise ValueError("invalid depth price/quantity")
                        if qty > 0:
                            updated[price] = qty
                    book[side] = updated
            elif event_type in {"cancel", "depletion"}:
                side = payload.get("side")
                if side not in {"bid", "ask"}:
                    raise ValueError("cancel/depletion side must be bid or ask")
                price, qty = float(payload["price"]), float(payload["quantity"])
                if not isfinite(price) or not isfinite(qty) or price <= 0 or qty < 0:
                    raise ValueError("invalid cancel/depletion values")
                left = max(0.0, book[side].get(price, 0.0) - qty)
                if left:
                    book[side][price] = left
                else:
                    book[side].pop(price, None)
            continue

        side = item.get("side")
        qty = float(item.get("quantity", 0))
        if side not in {"buy", "sell"} or not isfinite(qty) or qty <= 0:
            raise ValueError("order side/quantity invalid")
        levels = sorted(book["ask" if side == "buy" else "bid"].items(),
                        reverse=(side == "sell"))
        remaining, filled, notional = qty, 0.0, 0.0
        for price, available in levels:
            take = min(remaining, available)
            filled += take
            notional += take * price
            remaining -= take
            if remaining <= 1e-12:
                break
        vwap = notional / filled if filled else None
        fees = notional * fee_rate
        results.append({
            "timestamp_ns": ts, "side": side, "requested_quantity": qty,
            "filled_quantity": filled, "remaining_quantity": max(0.0, qty - filled),
            "vwap": vwap, "notional": notional, "fees": fees,
            "complete": filled >= qty * 0.999999,
        })
    return results
