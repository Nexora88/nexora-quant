"""In-memory runtime state; durable recovery is not implemented yet."""
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from app.events import BookTicker, TradeTick

class RuntimeState:
    def __init__(self) -> None:
        self.latest_book: BookTicker | None = None
        self.trades: deque[TradeTick] = deque(maxlen=1000)
        self.last_message_at = None
        self.connected = False
        self.reconnect_count = 0
        self.kill_switch = False
        self.kill_switch_reason = None
        self.events_seen = 0
        self.last_error = None
        self.executor = None
        self.risk_manager = None

    def update_book(self, book: BookTicker) -> None:
        self.latest_book = book
        self.last_message_at = book.received_at
        self.events_seen += 1

    def add_trade(self, trade: TradeTick) -> None:
        self.trades.append(trade)
        self.last_message_at = trade.received_at
        self.events_seen += 1

    def data_age_seconds(self) -> float | None:
        if self.last_message_at is None:
            return None
        return max(0.0, (datetime.now(timezone.utc) - self.last_message_at).total_seconds())

    def snapshot(self) -> dict:
        book = self.latest_book
        return {"mode": "paper", "connected": self.connected, "reconnect_count": self.reconnect_count, "events_seen": self.events_seen, "data_age_seconds": self.data_age_seconds(), "last_error": self.last_error, "kill_switch": self.kill_switch, "kill_switch_reason": self.kill_switch_reason, "market": asdict(book) if book else None, "portfolio": self.executor.snapshot(book.bid if book else None) if self.executor else None}
