#!/usr/bin/env python3
"""Paper-only: stream synchronized depth for SYMBOL + SYMBOLS and write L2 history.

Does not place orders. Use during the week to accumulate fixtures for L2 backtests.
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


async def _one(symbol: str, path: str) -> None:
    writer = MarketHistoryWriter(path)
    log.info("capturing symbol=%s path=%s", symbol, path)
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
                log.info("%s events=%s", symbol, n)
    finally:
        log.info("%s stopped events=%s", symbol, n)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    symbols = list(settings.watch_symbols())
    if not symbols:
        symbols = [settings.symbol]
    tasks = []
    for sym in symbols:
        path = settings.market_history_path if sym == settings.symbol else f"data/market-history-{sym}.jsonl.gz"
        tasks.append(asyncio.create_task(_one(sym, path), name=f"cap-{sym}"))
    log.info("watching %s", symbols)
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
