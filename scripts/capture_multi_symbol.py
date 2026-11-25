#!/usr/bin/env python3
"""Paper-only multi-symbol recorder for depth, executed trades and closed klines.

The resulting gzip JSONL can feed deterministic L2 research. It never places orders.
Run with Ctrl+C to flush and close all writers cleanly.
"""
from __future__ import annotations

import asyncio
import argparse
from hashlib import file_digest
import json
import logging
import re
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


async def _one(symbol: str, path: str, *, seconds: int | None = None, seed: bool = True) -> dict:
    writer = MarketHistoryWriter(path, max_pending=_MAX_PENDING)
    counts = {"depth": 0, "trade": 0, "kline": 0}
    disconnects = {"depth": 0, "market": 0}
    last_ns: int | None = None
    first_ns: int | None = None
    largest_gap_ns = 0
    last_row_ns = 0
    append_lock = asyncio.Lock()
    log.info("capturing symbol=%s path=%s", symbol.upper(), path)

    async def record(event_type: str, payload: dict) -> None:
        nonlocal last_row_ns
        async with append_lock:
            last_row_ns = max(last_row_ns, time.time_ns())
            writer.append(timestamp_ns=last_row_ns, event_type=event_type, payload=payload)
            counts[event_type] += 1
            count = sum(counts.values())
            if not count % _FLUSH_EVERY:
                writer.flush()
                log.info("%s events=%s writer=%s", symbol.upper(), count, writer.stats())

    # Seed enough closed candles for EMA200 and multi-timeframe context before
    # live recording starts; replay can then evaluate decisions immediately.
    for interval, limit in (("1m", 250), ("5m", 100)) if seed else ():
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
        nonlocal first_ns, last_ns, largest_gap_ns
        async for depth in stream_synchronized_depth(symbol, on_reconnect=depth_disconnected):
            if (
                not depth.synchronized or not depth.best_bid or not depth.best_ask
                or depth.age_seconds() > settings.max_data_age_seconds
            ):
                continue
            if first_ns is None:
                first_ns = depth.received_monotonic_ns
            if last_ns is not None:
                largest_gap_ns = max(largest_gap_ns, depth.received_monotonic_ns - last_ns)
            last_ns = depth.received_monotonic_ns
            bid, bid_qty = depth.best_bid
            ask, ask_qty = depth.best_ask
            await record("depth", {
                "symbol": symbol,
                "best_bid": [bid, bid_qty],
                "best_ask": [ask, ask_qty],
                "update_id": getattr(depth, "last_update_id", None),
                "exchange_at_ms": depth.exchange_at_ms,
                "received_at_ns": depth.received_at_ns,
                "bids": sorted(getattr(depth, "bids", {}).items(), reverse=True)[:20],
                "asks": sorted(getattr(depth, "asks", {}).items())[:20],
            })

    def depth_disconnected(_sym, _exc) -> None:
        disconnects["depth"] += 1

    def market_disconnected(_sym, _exc) -> None:
        disconnects["market"] += 1

    async def market_pump() -> None:
        async for event in stream_events(symbol, on_reconnect=market_disconnected):
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

    start_ns = time.monotonic_ns()
    tasks = [
        asyncio.create_task(depth_pump(), name=f"depth-{symbol}"),
        asyncio.create_task(market_pump(), name=f"market-{symbol}"),
    ]
    try:
        done, _ = await asyncio.wait(tasks, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
            raise RuntimeError(f"{task.get_name()} ended before the capture completed")
    finally:
        end_ns = time.monotonic_ns()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Do not retry a failed append/flush into a potentially partial archive.
        # Bounded mode never writes a manifest for a writer failure.
        if not any(task.done() and not task.cancelled() and task.exception() for task in tasks):
            writer.close()
        log.info("%s stopped events=%s stats=%s", symbol.upper(), sum(counts.values()), writer.stats())
    max_gap = max(
        largest_gap_ns, (first_ns or end_ns) - start_ns, end_ns - (last_ns or start_ns),
    ) / 1e9
    return {
        "symbol": symbol.upper(), "file": Path(path).name, "events": counts,
        "disconnects": disconnects, "duration_seconds": (end_ns - start_ns) / 1e9,
        "max_depth_gap_seconds": max_gap,
    }


async def _capture_bounded(args) -> int:
    args.output_dir.mkdir(parents=True, exist_ok=False)
    symbols = tuple(dict.fromkeys(args.symbol or [settings.symbol]))
    async with asyncio.TaskGroup() as group:
        captures = [
            group.create_task(_one(
                sym, str(args.output_dir / f"{sym}.jsonl.gz"), seconds=args.seconds, seed=not args.no_seed,
            ))
            for sym in symbols
        ]
    summaries = [task.result() for task in captures]
    for summary in summaries:
        path = args.output_dir / summary["file"]
        summary["sha256"] = None
        if path.is_file():
            with path.open("rb") as stream:
                summary["sha256"] = file_digest(stream, "sha256").hexdigest()
        summary["coverage_ok"] = (
            summary["sha256"] is not None
            and summary["events"]["depth"] >= args.min_depth_frames
            and summary["events"]["trade"] > 0
            and sum(summary["disconnects"].values()) == 0
            and summary["max_depth_gap_seconds"] <= args.max_depth_gap_seconds
        )
    manifest = {
        "schema_version": 1, "source": "binance_spot_public", "research_only": True,
        "min_depth_frames": args.min_depth_frames, "max_depth_gap_seconds": args.max_depth_gap_seconds,
        "coverage_ok": all(item["coverage_ok"] for item in summaries), "captures": summaries,
    }
    with (args.output_dir / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, allow_nan=False)
        stream.write("\n")
    log.info("capture manifest=%s coverage_ok=%s", args.output_dir / "manifest.json", manifest["coverage_ok"])
    return 0 if manifest["coverage_ok"] else 2


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, help="bounded recording duration after optional candle seed")
    parser.add_argument("--output-dir", type=Path, help="new output directory for a bounded capture")
    parser.add_argument("--symbol", action="append", type=str.lower, help="repeat to capture multiple pairs")
    parser.add_argument("--min-depth-frames", type=int, default=10)
    parser.add_argument("--max-depth-gap-seconds", type=float, default=5)
    parser.add_argument("--no-seed", action="store_true", help="skip closed-candle history seeding")
    args = parser.parse_args()
    if args.seconds is not None:
        if (
            not 1 <= args.seconds <= 604_800 or args.output_dir is None
            or args.min_depth_frames < 1 or not 0 < args.max_depth_gap_seconds <= 60
            or any(not re.fullmatch(r"[a-z0-9]{5,20}", sym) for sym in args.symbol or [])
        ):
            parser.error("bounded capture needs a new output dir, valid duration, symbols and coverage limits")
        return await _capture_bounded(args)
    if args.output_dir is not None or args.symbol or args.no_seed:
        parser.error("--output-dir, --symbol and --no-seed require --seconds")
    symbols = list(dict.fromkeys([*settings.watch_symbols(), "btcusdt", "ethusdt"]))
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
    return 0


if __name__ == "__main__":
    try:
        try:
            import uvloop  # type: ignore
            uvloop.install()
        except Exception:
            pass
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass
