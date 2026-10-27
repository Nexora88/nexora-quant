"""Concurrent multi-symbol synchronized depth fan-in.

Each watch symbol runs its own synchronized WS+snapshot task; depth books are
tagged and merged into one asyncio.Queue for the engine loop.

BTC is always included when any non-BTC alt is watched so the macro lock has a live mid.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.binance_depth import stream_synchronized_depth
from app.depth_book import DepthBook

log = logging.getLogger(__name__)


@dataclass(slots=True)
class TaggedDepth:
    symbol: str
    book: DepthBook


async def _pump(symbol: str, out: asyncio.Queue[TaggedDepth], stop: asyncio.Event) -> None:
    sym = symbol.lower()
    try:
        async for book in stream_synchronized_depth(sym):
            if stop.is_set():
                break
            if not book.synchronized:
                continue
            try:
                out.put_nowait(TaggedDepth(sym, book))
            except asyncio.QueueFull:
                try:
                    out.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    out.put_nowait(TaggedDepth(sym, book))
                except asyncio.QueueFull:
                    pass
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("depth pump crashed symbol=%s", sym.upper())
        await asyncio.sleep(1.0)


def watch_list(primary: str, extras: tuple[str, ...] | list[str]) -> list[str]:
    """Deduped symbols; ensure btcusdt is present when trading alts."""
    out: list[str] = []
    for s in [primary, *extras]:
        s = (s or "").strip().lower()
        if s and s not in out:
            out.append(s)
    if any(s != "btcusdt" for s in out) and "btcusdt" not in out:
        out.append("btcusdt")
    return out


async def stream_multi_depth(
    symbols: list[str],
    *,
    max_queue: int = 2000,
) -> AsyncIterator[TaggedDepth]:
    """Yield TaggedDepth from all symbols concurrently until cancelled."""
    if not symbols:
        raise ValueError("symbols required")
    q: asyncio.Queue[TaggedDepth] = asyncio.Queue(maxsize=max_queue)
    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(_pump(sym, q, stop), name=f"depth-{sym}")
        for sym in symbols
    ]
    log.info("Multi-depth pumps started: %s", ",".join(s.upper() for s in symbols))
    try:
        while True:
            item = await q.get()
            yield item
    finally:
        stop.set()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
