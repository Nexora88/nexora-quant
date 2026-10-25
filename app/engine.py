"""Orchestration. All execution in this release is simulated."""
import asyncio
import logging
from app.binance_ws import stream_events
from app.config import settings
from app.events import BookTicker, TradeTick
from app.paper import PaperExecutor
from app.risk import RiskManager
from app.state import RuntimeState
from app.strategy import evaluate_imbalance

log = logging.getLogger(__name__)
state = RuntimeState()
executor = PaperExecutor(settings.starting_cash_usdt, settings.fee_rate)
risk = RiskManager(max_order_size_usdt=settings.max_order_size_usdt, max_daily_loss_usdt=settings.max_daily_loss_usdt, max_consecutive_losses=settings.max_consecutive_losses, max_spread_bps=settings.max_spread_bps, max_data_age_seconds=settings.max_data_age_seconds)
state.executor = executor
state.risk_manager = risk

async def run() -> None:
    async for event in stream_events(settings.symbol):
        state.connected = True
        if isinstance(event, TradeTick):
            state.add_trade(event)
            continue
        if isinstance(event, BookTicker):
            state.update_book(event)
            signal = evaluate_imbalance(event.bid_qty, event.ask_qty, settings.imbalance_threshold)
            if signal is None or executor.base_quantity > 0:
                continue
            decision = risk.evaluate_entry(notional_usdt=settings.order_size_usdt, available_cash=executor.cash_usdt, bid=event.bid, ask=event.ask, data_age_seconds=state.data_age_seconds())
            if decision.allowed:
                trade = executor.buy(notional_usdt=settings.order_size_usdt, price=event.ask, reason=signal.reason)
                log.info("PAPER BUY %s qty=%.8f price=%.4f", event.symbol.upper(), trade["quantity"], event.ask)
            else:
                log.debug("Paper entry rejected: %s", decision.reason)
        await asyncio.sleep(0)
