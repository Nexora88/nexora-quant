#!/usr/bin/env python3
"""Paper-only multi-symbol recorder for depth, executed trades and closed klines.

The resulting gzip JSONL can feed deterministic L2 research. It never places orders.
Run with Ctrl+C to flush and close all writers cleanly.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.binance_depth import stream_synchronized_depth
from app.binance_ws import stream_events
from app.config import settings
from app.events import KlineTick, TradeTick
from app.market_history import MarketHistoryWriter
from app.market_indicators import fetch_recent_candles

log = logging.getLogger("capture_multi")
_MAX_PENDING = 50_000
_FLUSH_EVERY = 500


async def _one(symbol: str, path: str) -> None:
    writer = MarketHistoryWriter(path, max_pending=_MAX_PENDING)
    count = 0
    append_lock = asyncio.Lock()
    log.info("capturing symbol=%s path=%s", symbol.upper(), path)

    async def record(event_type: str, payload: dict) -> None:
        nonlocal count
        async with append_lock:
            writer.append(timestamp_ns=time.time_ns(), event_type=event_type, payload=payload)
            count += 1
            if count % _FLUSH_EVERY == 0:
                writer.flush()
                log.info("%s events=%s writer=%s", symbol.upper(), count, writer.stats())

    # Seed enough closed candles for EMA200 and multi-timeframe context before
    # live recording starts; replay can then evaluate decisions immediately.
    for interval, limit in (("1m", 250), ("5m", 100)):
        try:
            candles = await asyncio.to_thread(
                fetch_recent_candles, symbol, interval, limit=limit,
            )
            for candle in candles:
                await record("kline", {
                    "symbol": candle.symbol,
                    "interval": candle.interval,
                    "open_time": candle.open_time,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                    "closed": True,
                    "received_at": candle.received_at,
                })
            log.info("%s seeded %s closed candles: %s", symbol.upper(), interval, len(candles))
        except Exception as exc:
            log.warning("%s %s candle seed unavailable: %s", symbol.upper(), interval, exc)

    async def depth_pump() -> None:
        async for depth in stream_synchronized_depth(symbol):
            if not depth.synchronized or not depth.best_bid or not depth.best_ask:
                continue
            bid, bid_qty = depth.best_bid
            ask, ask_qty = depth.best_ask
            await record("depth", {
                "symbol": symbol,
                "best_bid": [bid, bid_qty],
                "best_ask": [ask, ask_qty],
                "update_id": getattr(depth, "last_update_id", None),
                "bids": sorted(getattr(depth, "bids", {}).items(), reverse=True)[:20],
                "asks": sorted(getattr(depth, "asks", {}).items())[:20],
            })

    async def market_pump() -> None:
        async for event in stream_events(symbol):
            if isinstance(event, TradeTick):
                await record("trade", {
                    "symbol": event.symbol,
                    "price": event.price,
                    "quantity": event.quantity,
                    "buyer_is_maker": event.buyer_is_maker,
                    "received_at": event.received_at.timestamp(),
                })
            elif isinstance(event, KlineTick) and event.closed:
                await record("kline", {
                    "symbol": event.symbol,
                    "interval": event.interval,
                    "open_time": event.open_time,
                    "open": event.open,
                    "high": event.high,
                    "low": event.low,
                    "close": event.close,
                    "volume": event.volume,
                    "closed": True,
                    "received_at": event.received_at.timestamp(),
                })

    tasks = [
        asyncio.create_task(depth_pump(), name=f"depth-{symbol}"),
        asyncio.create_task(market_pump(), name=f"market-{symbol}"),
    ]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            exc = task.exception()
            if exc:
                raise exc
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        writer.close()
        log.info("%s stopped events=%s dropped=%s", symbol.upper(), count, writer.stats()["dropped"])


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    symbols = list(settings.watch_symbols())
    if not symbols:
        symbols = [settings.symbol]
    tasks = []
    for symbol in symbols:
        path = (
            settings.market_history_path
            if symbol == settings.symbol
            else f"data/market-history-{symbol}.jsonl.gz"
        )
        tasks.append(asyncio.create_task(_one(symbol, path), name=f"capture-{symbol}"))
    log.info("recording symbols=%s; Ctrl+C to stop", ",".join(s.upper() for s in symbols))
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
