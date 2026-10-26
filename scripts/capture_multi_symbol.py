#!/usr/bin/env python3
"""Paper-only: stream synchronized depth for SYMBOL + SYMBOLS and write L2 history.

Does not place orders. Bounded per-symbol buffers drop oldest under volume spikes
so multi-pair capture cannot OOM the host.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.binance_depth import stream_synchronized_depth
from app.config import settings
from app.market_history import MarketHistoryWriter

log = logging.getLogger("capture_multi")

# Per-symbol pending cap (records). 4 pairs × 8k ≈ bounded RAM under stress.
_MAX_PENDING = 8000


async def _one(symbol: str, path: str) -> None:
    writer = MarketHistoryWriter(path, max_pending=_MAX_PENDING)
    log.info("capturing symbol=%s path=%s max_pending=%s", symbol, path, _MAX_PENDING)
    n = 0
    try:
        async for depth in stream_synchronized_depth(symbol):
            if not depth.synchronized or not depth.best_bid or not depth.best_ask:
                continue
            bid, bq = depth.best_bid
            ask, aq = depth.best_ask
            writer.append(
                timestamp_ns=time.time_ns(),
                event_type="depth",
                payload={
                    "symbol": symbol,
                    "best_bid": [bid, bq],
                    "best_ask": [ask, aq],
                    "update_id": getattr(depth, "last_update_id", None),
                    "bids": sorted(getattr(depth, "bids", {}).items(), reverse=True)[:20],
                    "asks": sorted(getattr(depth, "asks", {}).items())[:20],
                },
            )
            n += 1
            if n % 500 == 0:
                st = writer.stats()
                log.info("%s events=%s writer=%s", symbol, n, st)
    finally:
        writer.close()
        log.info("%s stopped events=%s dropped=%s", symbol, n, writer.stats().get("dropped"))


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    symbols = list(settings.watch_symbols())
    if not symbols:
        symbols = [settings.symbol]
    tasks = []
    for sym in symbols:
        path = (
            settings.market_history_path
            if sym == settings.symbol
            else f"data/market-history-{sym}.jsonl.gz"
        )
        tasks.append(asyncio.create_task(_one(sym, path), name=f"cap-{sym}"))
    log.info("watching %s max_pending_each=%s", symbols, _MAX_PENDING)
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        try:
            import uvloop  # type: ignore

            uvloop.install()
        except Exception:
            pass
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
