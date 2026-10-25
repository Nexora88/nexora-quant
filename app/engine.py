"""Paper engine using synchronized public depth data and durable paper state."""
import asyncio
import logging
from datetime import datetime, timezone
from app.binance_depth import stream_synchronized_depth
from app.config import settings
from app.events import BookTicker
from app.paper import PaperExecutor
from app.portfolio import size_from_free_cash
from app.risk import RiskManager
from app.state import RuntimeState
from app.storage import PaperStore
from app.strategy import evaluate_imbalance

log = logging.getLogger(__name__)
state = RuntimeState()
executor = PaperExecutor(settings.starting_cash_usdt, settings.fee_rate)
risk = RiskManager(max_order_size_usdt=settings.max_order_size_usdt, max_daily_loss_usdt=settings.max_daily_loss_usdt, max_consecutive_losses=settings.max_consecutive_losses, max_spread_bps=settings.max_spread_bps, max_data_age_seconds=settings.max_data_age_seconds)
state.executor, state.risk_manager = executor, risk

async def run() -> None:
    store = PaperStore(settings.store_path)
    key = f"paper:{settings.symbol}"
    saved = store.load_state(key)
    if saved:
        executor.restore(saved["account"])
        r = saved.get("risk", {})
        risk.realized_pnl_today = float(r.get("realized_pnl_today", 0))
        risk.consecutive_losses = int(r.get("consecutive_losses", 0))
        risk.kill_switch = bool(r.get("kill_switch", False))
        risk.kill_switch_reason = r.get("kill_switch_reason")
    def persist() -> None:
        store.save_state(key, {"account": executor.snapshot(), "risk": {"realized_pnl_today": risk.realized_pnl_today, "consecutive_losses": risk.consecutive_losses, "kill_switch": risk.kill_switch, "kill_switch_reason": risk.kill_switch_reason}, "saved_at": datetime.now(timezone.utc).isoformat()})
    try:
        async for depth in stream_synchronized_depth(settings.symbol):
            if not depth.synchronized or not depth.best_bid or not depth.best_ask:
                continue
            bid, bid_qty = depth.best_bid
            ask, ask_qty = depth.best_ask
            if ask < bid:
                continue
            state.update_book(BookTicker(settings.symbol, bid, bid_qty, ask, ask_qty, datetime.now(timezone.utc)))
            if executor.base_quantity > 0 and executor.average_entry_price > 0:
                move = (bid / executor.average_entry_price - 1) * 100
                reason = "take_profit" if move >= settings.take_profit_pct else "stop_loss" if move <= -settings.stop_loss_pct else None
                if reason:
                    trade = executor.sell_all(price=bid, reason=reason)
                    if trade:
                        store.append_trade(trade, event_key=f"{key}:{trade['timestamp']}:{trade['side']}:{trade['quantity']:.12f}")
                        risk.record_closed_trade(float(trade.get("pnl_usdt", 0)))
            signal = evaluate_imbalance(bid_qty, ask_qty, settings.imbalance_threshold)
            if signal and executor.base_quantity <= 0 and not risk.kill_switch:
                sizing = size_from_free_cash(free_usdt=executor.cash_usdt, allocation_fraction=0.8, fee_rate=settings.fee_rate, max_order_usdt=min(settings.order_size_usdt, settings.max_order_size_usdt), min_order_usdt=5)
                if sizing.notional_usdt > 0:
                    decision = risk.evaluate_entry(notional_usdt=sizing.notional_usdt, available_cash=executor.cash_usdt, bid=bid, ask=ask, data_age_seconds=state.data_age_seconds())
                    if decision.allowed:
                        trade = executor.buy(notional_usdt=sizing.notional_usdt, price=ask, reason=signal.reason)
                        store.append_trade(trade, event_key=f"{key}:{trade['timestamp']}:{trade['side']}:{trade['quantity']:.12f}")
            persist()
            await asyncio.sleep(0)
    finally:
        persist()
        store.close()
