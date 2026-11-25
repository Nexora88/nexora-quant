"""Synchronized Binance Spot depth stream (public data only).

Connect first and buffer diff events, fetch a REST snapshot, discard events already
covered by the snapshot, then bridge the snapshot update ID with the first diff.
Any sequence gap forces a full resynchronization. No credentials or order endpoints.
"""
import asyncio
import json
import logging
import random
import time
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import AsyncIterator, Callable
from typing import Any

import websockets

from app.binance_rest import TESTNET_REST
from app.depth_book import DepthBook, DepthSnapshot

log = logging.getLogger(__name__)
WS_BASE = "wss://stream.binance.com:9443/ws"
TESTNET_WS_BASE = "wss://stream.testnet.binance.vision/ws"
REST_BASE = "https://api.binance.com/api/v3/depth"
SNAPSHOT_LIMIT = 1000
BUFFER_LIMIT = 20_000


def _snapshot(symbol: str, *, testnet: bool = False) -> dict[str, Any]:
    query = urllib.parse.urlencode({"symbol": symbol.upper(), "limit": SNAPSHOT_LIMIT})
    endpoint = f"{TESTNET_REST}/api/v3/depth" if testnet else REST_BASE
    request = urllib.request.Request(f"{endpoint}?{query}", headers={"User-Agent": "NexoraQuant/0.1"})
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data.get("lastUpdateId"), int):
        raise ValueError("Invalid Binance depth snapshot")
    return data


def _levels(values: list[list[str]]) -> list[tuple[float, float]]:
    return [(float(price), float(quantity)) for price, quantity in values]


def _apply_depth_event(book: DepthBook, event: dict[str, Any]) -> bool:
    """Ignore already-applied duplicate/stale events; reject only a real gap."""
    first_id = int(event["U"])
    final_id = int(event["u"])
    if book.last_update_id is not None and final_id <= book.last_update_id:
        return True
    return book.apply_diff(
        first_update_id=first_id,
        final_update_id=final_id,
        bids=_levels(event["b"]),
        asks=_levels(event["a"]),
    )


async def stream_synchronized_depth(
    symbol: str,
    *,
    on_reconnect: Callable[[str, Exception], None] | None = None,
    testnet: bool = False,
) -> AsyncIterator[DepthSnapshot]:
    """Publish immutable top levels; the mutable full book never leaves this stream."""
    backoff = 1.0
    symbol = symbol.lower()
    url = f"{TESTNET_WS_BASE if testnet else WS_BASE}/{symbol}@depth@100ms"
    last_published_id = -1
    while True:
        try:
            async with websockets.connect(
                url, ping_interval=20, ping_timeout=20, close_timeout=5,
                max_size=4_000_000,
            ) as socket:
                buffer: deque[tuple[dict[str, Any], int, int]] = deque()
                # The snapshot has no exchange timestamp; bound its age by the
                # request start, not by the end of a potentially slow REST call.
                received_at_ns, received_mono_ns = time.time_ns(), time.monotonic_ns()
                exchange_at_ms = None
                rest_options = {"testnet": True} if testnet else {}
                snapshot_task = asyncio.create_task(asyncio.to_thread(_snapshot, symbol, **rest_options))
                try:
                    while not snapshot_task.done():
                        try:
                            raw = await asyncio.wait_for(socket.recv(), timeout=0.25)
                        except asyncio.TimeoutError:
                            continue
                        wall_ns, mono_ns = time.time_ns(), time.monotonic_ns()
                        event = json.loads(raw)
                        if event.get("e") == "depthUpdate":
                            buffer.append((event, wall_ns, mono_ns))
                            if len(buffer) > BUFFER_LIMIT:
                                raise RuntimeError("Depth buffer overflow; restarting synchronization")
                    snapshot = await snapshot_task
                finally:
                    if not snapshot_task.done():
                        snapshot_task.cancel()
                    await asyncio.gather(snapshot_task, return_exceptions=True)
                book = DepthBook(symbol=symbol)
                book.load_snapshot(
                    last_update_id=snapshot["lastUpdateId"],
                    bids=_levels(snapshot["bids"]),
                    asks=_levels(snapshot["asks"]),
                )
                # Binance bridge rule: first event must span lastUpdateId + 1.
                while buffer:
                    event, wall_ns, mono_ns = buffer.popleft()
                    first_id, final_id = int(event["U"]), int(event["u"])
                    if final_id <= book.last_update_id:
                        continue
                    if not book.apply_diff(
                        first_update_id=first_id,
                        final_update_id=final_id,
                        bids=_levels(event["b"]),
                        asks=_levels(event["a"]),
                    ):
                        book.synchronized = False
                        break
                    received_at_ns, received_mono_ns = wall_ns, mono_ns
                    exchange_at_ms = int(event["E"]) if "E" in event else None
                if not book.synchronized:
                    raise RuntimeError("Depth snapshot buffer could not be bridged")
                backoff = 1.0
                log.info("Synchronized %s depth at update ID %s", symbol.upper(), book.last_update_id)
                if book.last_update_id > last_published_id:
                    last_published_id = book.last_update_id
                    yield book.publish(
                        received_at_ns=received_at_ns, received_monotonic_ns=received_mono_ns,
                        exchange_at_ms=exchange_at_ms, testnet=testnet,
                    )
                async for raw in socket:
                    wall_ns, mono_ns = time.time_ns(), time.monotonic_ns()
                    event = json.loads(raw)
                    if event.get("e") != "depthUpdate":
                        continue
                    previous_id = book.last_update_id
                    accepted = _apply_depth_event(book, event)
                    if not accepted:
                        raise RuntimeError(
                            "Binance depth sequence gap; "
                            f"local={previous_id} event_U={event.get('U')} event_u={event.get('u')}; "
                            "resynchronizing"
                        )
                    if book.last_update_id <= last_published_id:
                        continue
                    last_published_id = book.last_update_id
                    yield book.publish(
                        received_at_ns=wall_ns, received_monotonic_ns=mono_ns,
                        exchange_at_ms=int(event["E"]) if "E" in event else None,
                        testnet=testnet,
                    )
                raise ConnectionError("Binance depth websocket closed")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Depth stream unavailable symbol=%s (%s); retrying", symbol.upper(), exc)
            if on_reconnect is not None:
                try:
                    on_reconnect(symbol.lower(), exc)
                except Exception:
                    log.exception("Depth reconnect callback failed symbol=%s", symbol.upper())
            await asyncio.sleep(min(backoff, 30.0) + random.uniform(0, 0.25))
            backoff = min(backoff * 2, 30.0)
