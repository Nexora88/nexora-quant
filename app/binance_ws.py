"""Public Binance Spot WebSocket adapter with reconnect/backoff."""
import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator
import websockets
from app.events import BookTicker, TradeTick, KlineTick, utc_now

log = logging.getLogger(__name__)
BASE_URL = "wss://stream.binance.com:9443/stream?streams="

def parse_message(message: str) -> BookTicker | TradeTick | KlineTick:
    envelope = json.loads(message)
    data = envelope.get("data", envelope)
    if data.get("e") == "bookTicker" or {"b", "B", "a", "A"} <= data.keys():
        return BookTicker(data.get("s", "").lower(), float(data["b"]), float(data["B"]), float(data["a"]), float(data["A"]), utc_now())
    if data.get("e") == "trade" or {"p", "q", "m"} <= data.keys():
        return TradeTick(data.get("s", "").lower(), float(data["p"]), float(data["q"]), bool(data["m"]), utc_now())
    if data.get("e") == "kline" and isinstance(data.get("k"), dict):
        k = data["k"]
        return KlineTick(
            data.get("s", "").lower(), str(k["i"]), int(k["t"]),
            float(k["o"]), float(k["h"]), float(k["l"]),
            float(k["c"]), float(k["v"]), bool(k["x"]), utc_now(),
        )
    raise ValueError("Unsupported Binance stream event")

async def stream_events(symbol: str) -> AsyncIterator[BookTicker | TradeTick | KlineTick]:
    streams = f"{symbol.lower()}@bookTicker/{symbol.lower()}@trade/{symbol.lower()}@kline_1m/{symbol.lower()}@kline_5m"
    url = BASE_URL + streams
    backoff = 1.0
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, close_timeout=5, max_size=1_000_000) as socket:
                log.info("Connected to Binance public stream for %s", symbol.upper())
                backoff = 1.0
                async for raw in socket:
                    try:
                        yield parse_message(raw)
                    except (ValueError, KeyError, TypeError) as exc:
                        log.warning("Skipping malformed market event: %s", exc)
                raise ConnectionError("Binance market websocket closed")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            delay = min(backoff, 60.0) + random.uniform(0, 0.25)
            log.warning("Market stream disconnected (%s); reconnecting in %.2fs", exc, delay)
            await asyncio.sleep(delay)
            backoff = min(backoff * 2, 60.0)
