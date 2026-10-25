"""Synchronized Binance Spot depth stream (public data only).

Connect first and buffer diff events, fetch a REST snapshot, discard events already
covered by the snapshot, then bridge the snapshot update ID with the first diff.
Any sequence gap forces a full resynchronization. No credentials or order endpoints.
"""
import asyncio
import json
import logging
import random
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

import websockets

from app.depth_book import DepthBook

log = logging.getLogger(__name__)
WS_BASE = "wss://stream.binance.com:9443/ws"
REST_BASE = "https://api.binance.com/api/v3/depth"
SNAPSHOT_LIMIT = 1000
BUFFER_LIMIT = 20_000


def _snapshot(symbol: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"symbol": symbol.upper(), "limit": SNAPSHOT_LIMIT})
    request = urllib.request.Request(f"{REST_BASE}?{query}", headers={"User-Agent": "NexoraQuant/0.1"})
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data.get("lastUpdateId"), int):
        raise ValueError("Invalid Binance depth snapshot")
    return data


def _levels(values: list[list[str]]) -> list[tuple[float, float]]:
    return [(float(price), float(quantity)) for price, quantity in values]


async def stream_synchronized_depth(symbol: str) -> AsyncIterator[DepthBook]:
    """Yield only synchronized books. Reconnect and re-snapshot on any gap."""
    backoff = 1.0
    url = f"{WS_BASE}/{symbol.lower()}@depth@100ms"
    while True:
        try:
            async with websockets.connect(
                url, ping_interval=20, ping_timeout=20, close_timeout=5,
                max_size=4_000_000,
            ) as socket:
                buffer: deque[dict[str, Any]] = deque()
                snapshot_task = asyncio.create_task(asyncio.to_thread(_snapshot, symbol))
                # The socket is already connected while REST snapshot is fetched.
                while not snapshot_task.done():
                    try:
                        raw = await asyncio.wait_for(socket.recv(), timeout=0.25)
                    except asyncio.TimeoutError:
                        continue
                    event = json.loads(raw)
                    if event.get("e") == "depthUpdate":
                        buffer.append(event)
                        if len(buffer) > BUFFER_LIMIT:
                            raise RuntimeError("Depth buffer overflow; restarting synchronization")
                snapshot = await snapshot_task
                book = DepthBook()
                book.load_snapshot(
                    last_update_id=snapshot["lastUpdateId"],
                    bids=_levels(snapshot["bids"]),
                    asks=_levels(snapshot["asks"]),
                )
                # Binance bridge rule: first event must span lastUpdateId + 1.
                while buffer and int(buffer[0]["u"]) <= book.last_update_id:
                    buffer.popleft()
                while buffer:
                    event = buffer.popleft()
                    first_id, final_id = int(event["U"]), int(event["u"])
                    if final_id <= book.last_update_id:
                        continue
                    if first_id > book.last_update_id + 1:
                        book.synchronized = False
                        break
                    if not book.apply_diff(
                        first_update_id=first_id,
                        final_update_id=final_id,
                        bids=_levels(event["b"]),
                        asks=_levels(event["a"]),
                    ):
                        book.synchronized = False
                        break
                if not book.synchronized:
                    raise RuntimeError("Depth snapshot buffer could not be bridged")
                backoff = 1.0
                log.info("Synchronized %s depth at update ID %s", symbol.upper(), book.last_update_id)
                yield book
                async for raw in socket:
                    event = json.loads(raw)
                    if event.get("e") != "depthUpdate":
                        continue
                    accepted = book.apply_diff(
                        first_update_id=int(event["U"]),
                        final_update_id=int(event["u"]),
                        previous_final_update_id=int(event["pu"]) if "pu" in event else None,
                        bids=_levels(event["b"]),
                        asks=_levels(event["a"]),
                    )
                    if not accepted:
                        raise RuntimeError("Binance depth sequence gap; resynchronizing")
                    yield book
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Depth stream unavailable (%s); retrying", exc)
            await asyncio.sleep(min(backoff, 30.0) + random.uniform(0, 0.25))
            backoff = min(backoff * 2, 30.0)
