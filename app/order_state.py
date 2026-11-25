"""Explicit, fail-closed lifecycle tracking for one live exchange order intent."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OrderState(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


_TERMINAL = {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED}
_ALLOWED = {
    OrderState.PENDING: {
        OrderState.PENDING, OrderState.OPEN, OrderState.PARTIALLY_FILLED, OrderState.FILLED,
        OrderState.CANCELLED, OrderState.REJECTED, OrderState.UNKNOWN,
    },
    OrderState.OPEN: {
        OrderState.PARTIALLY_FILLED, OrderState.FILLED,
        OrderState.CANCELLED, OrderState.REJECTED, OrderState.UNKNOWN,
    },
    OrderState.PARTIALLY_FILLED: {
        OrderState.PARTIALLY_FILLED, OrderState.FILLED,
        OrderState.CANCELLED, OrderState.UNKNOWN,
    },
    OrderState.UNKNOWN: set(OrderState),
    OrderState.FILLED: {OrderState.FILLED},
    OrderState.CANCELLED: {OrderState.CANCELLED},
    OrderState.REJECTED: {OrderState.REJECTED},
}
_EXCHANGE = {
    "PENDING_NEW": OrderState.PENDING,
    "NEW": OrderState.OPEN,
    "PARTIALLY_FILLED": OrderState.PARTIALLY_FILLED,
    "FILLED": OrderState.FILLED,
    "CANCELED": OrderState.CANCELLED,
    "CANCELLED": OrderState.CANCELLED,
    "EXPIRED": OrderState.CANCELLED,
    "EXPIRED_IN_MATCH": OrderState.CANCELLED,
    "REJECTED": OrderState.REJECTED,
}


@dataclass
class OrderStateMachine:
    """Tracks the latest intent; UNKNOWN is sticky until exchange reconciliation."""

    state: OrderState = OrderState.UNKNOWN
    client_order_id: str | None = None
    exchange_status: str | None = None

    @property
    def terminal(self) -> bool:
        return self.state in _TERMINAL

    @property
    def blocks_new_orders(self) -> bool:
        return self.state in {
            OrderState.PENDING, OrderState.OPEN, OrderState.PARTIALLY_FILLED,
            OrderState.UNKNOWN,
        }

    def begin(self, client_order_id: str) -> None:
        if not client_order_id:
            raise ValueError("client_order_id is required")
        if self.blocks_new_orders and self.client_order_id is not None:
            raise RuntimeError("Previous order intent is not terminal; new order blocked")
        self.client_order_id = client_order_id
        self.exchange_status = None
        self.state = OrderState.PENDING

    def observe(self, exchange_status: str) -> OrderState:
        raw = str(exchange_status or "").upper()
        next_state = _EXCHANGE.get(raw, OrderState.UNKNOWN)
        if next_state not in _ALLOWED[self.state]:
            raise RuntimeError(
                f"Invalid order state transition {self.state.value}->{next_state.value}"
            )
        self.state = next_state
        self.exchange_status = raw or None
        return self.state

    def mark_unknown(self, client_order_id: str | None = None) -> None:
        if client_order_id:
            self.client_order_id = client_order_id
        if OrderState.UNKNOWN not in _ALLOWED[self.state]:
            raise RuntimeError(f"Cannot mark {self.state.value} order UNKNOWN")
        self.state = OrderState.UNKNOWN
        self.exchange_status = None

    def force_unknown(self, client_order_id: str | None = None) -> None:
        self.client_order_id = client_order_id or self.client_order_id
        self.state = OrderState.UNKNOWN
        self.exchange_status = None

    def snapshot(self) -> dict[str, str | None]:
        return {
            "state": self.state.value,
            "client_order_id": self.client_order_id,
            "exchange_status": self.exchange_status,
        }

    def restore(self, data: dict) -> None:
        raw_state = str(data.get("state", "UNKNOWN")).upper()
        self.state = OrderState(raw_state)
        self.client_order_id = data.get("client_order_id")
        self.exchange_status = data.get("exchange_status")
        if self.state in _TERMINAL and not self.client_order_id:
            raise ValueError("Terminal order snapshot must retain client_order_id")
