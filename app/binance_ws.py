"""Public Binance Spot WebSocket adapter with reconnect/backoff."""
import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator
import websockets
from app.events import BookTicker, TradeTick, utc_now

log = logging.getLogger(__name__)
BASE_URL = "wss://stream.binance.com:9443/stream?streams="

def parse_message(message: str) -> BookTicker | TradeTick:
    envelope = json.loads(message)
    data = envelope.get("data", envelope)
    if data.get("e") == "bookTicker" or {"b", "B", "a", "A"} <= data.keys():
        return BookTicker(data.get("s", "").lower(), float(data["b"]), float(data["B"]), float(data["a"]), float(data["A"]), utc_now())
    if data.get("e") == "trade" or {"p", "q", "m"} <= data.keys():
        return TradeTick(data.get("s", "").lower(), float(data["p"]), float(data["q"]), bool(data["m"]), utc_now())
    raise ValueError("Unsupported Binance stream event")

async def stream_events(symbol: str) -> AsyncIterator[BookTicker | TradeTick]:
    streams = f"{symbol.lower()}@bookTicker/{symbol.lower()}@trade"
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
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            delay = min(backoff, 60.0) + random.uniform(0, 0.25)
            log.warning("Market stream disconnected (%s); reconnecting in %.2fs", exc, delay)
            await asyncio.sleep(delay)
            backoff = min(backoff * 2, 60.0)
