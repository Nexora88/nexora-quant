"""Typed domain models shared by market data, strategies, and execution."""
from dataclasses import dataclass
from datetime import datetime, timezone

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

@dataclass(frozen=True, slots=True)
class BookTicker:
    symbol: str
    bid: float
    bid_qty: float
    ask: float
    ask_qty: float
    received_at: datetime

@dataclass(frozen=True, slots=True)
class TradeTick:
    symbol: str
    price: float
    quantity: float
    buyer_is_maker: bool
    received_at: datetime

@dataclass(frozen=True, slots=True)
class Signal:
    action: str
    reason: str
    strength: float
    created_at: datetime
