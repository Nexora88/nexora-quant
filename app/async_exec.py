"""Fire-and-forget live order tasks so the depth loop is not blocked on REST RTT."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

log = logging.getLogger(__name__)


async def fire_live_buy(
    *,
    executor: Any,
    notional_usdt: float,
    price: float,
    reason: str,
    take_profit_pct: float,
    stop_loss_pct: float,
    on_fill: Callable[[dict], None] | None = None,
) -> dict | None:
    try:
        trade = await asyncio.to_thread(
            executor.buy, notional_usdt=notional_usdt, price=price, reason=reason
        )
        if trade and on_fill:
            on_fill(trade)
        if trade:
            qty = float(trade.get("quantity") or 0)
            px = float(trade.get("price") or price)
            await asyncio.to_thread(
                executor.place_protective_orders,
                quantity=qty,
                entry_price=px,
                take_profit_pct=take_profit_pct,
                stop_loss_pct=stop_loss_pct,
            )
        return trade
    except Exception:
        log.exception("fire_live_buy failed")
        return None


async def fire_live_sell(
    *,
    executor: Any,
    quantity: float,
    price: float,
    reason: str,
    on_fill: Callable[[dict], None] | None = None,
) -> dict | None:
    try:
        trade = await asyncio.to_thread(
            executor.sell_quantity, quantity=quantity, price=price, reason=reason
        )
        if trade and on_fill:
            on_fill(trade)
        return trade
    except Exception:
        log.exception("fire_live_sell failed")
        return None
