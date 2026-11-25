"""Concurrent multi-symbol synchronized depth fan-in.

Each watch symbol runs its own synchronized WS+snapshot task; depth books are
tagged and merged into one asyncio.Queue for the engine loop.

BTC is always included when any non-BTC alt is watched so the macro lock has a live mid.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from app.binance_depth import stream_synchronized_depth
from app.depth_book import DepthSnapshot

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TaggedDepth:
    symbol: str
    book: DepthSnapshot
    generation: int = 0


async def _pump(
    symbol: str,
    out: asyncio.Queue[TaggedDepth],
    stop: asyncio.Event,
    on_reconnect: Callable[[str, Exception], None] | None = None,
    *,
    generations: dict[str, int],
    on_drop: Callable[[str, str], None] | None = None,
    testnet: bool = False,
) -> None:
    """Keep a single-symbol depth pump alive across transient WS failures."""
    sym = symbol.lower()
    backoff = 1.0

    def reconnect(_symbol: str, exc: Exception) -> None:
        generations[sym] = generations.get(sym, 0) + 1
        if on_reconnect is not None:
            on_reconnect(sym, exc)

    while not stop.is_set():
        try:
            options = {"testnet": True} if testnet else {}
            async for book in stream_synchronized_depth(sym, on_reconnect=reconnect, **options):
                if stop.is_set():
                    return
                backoff = 1.0
                item = TaggedDepth(sym, book, generations.get(sym, 0))
                try:
                    out.put_nowait(item)
                except asyncio.QueueFull:
                    dropped = out.get_nowait()
                    out.put_nowait(item)
                    if on_drop is not None:
                        on_drop(dropped.symbol, "queue_overflow")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("depth pump crashed symbol=%s; reconnect in %.1fs", sym.upper(), backoff)
            reconnect(sym, exc)
            await asyncio.sleep(backoff)
            backoff = min(30.0, backoff * 1.5)


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
    on_reconnect: Callable[[str, Exception], None] | None = None,
    on_drop: Callable[[str, str], None] | None = None,
    testnet: bool = False,
) -> AsyncIterator[TaggedDepth]:
    """Yield TaggedDepth from all symbols concurrently until cancelled."""
    if not symbols:
        raise ValueError("symbols required")
    if max_queue < 1:
        raise ValueError("max_queue must be positive")
    q: asyncio.Queue[TaggedDepth] = asyncio.Queue(maxsize=max_queue)
    stop = asyncio.Event()
    generations: dict[str, int] = {}
    tasks = [
        asyncio.create_task(
            _pump(sym, q, stop, on_reconnect, generations=generations, on_drop=on_drop, testnet=testnet),
            name=f"depth-{sym}",
        )
        for sym in dict.fromkeys(symbol.lower() for symbol in symbols)
    ]
    log.info("Multi-depth pumps started: %s", ",".join(s.upper() for s in symbols))
    try:
        while True:
            item = await q.get()
            if item.generation != generations.get(item.symbol, 0):
                if on_drop is not None:
                    on_drop(item.symbol, "before_resync")
                continue
            yield item
    finally:
        stop.set()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
