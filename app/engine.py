"""Paper engine with synchronized depth, execution friction and durable risk state."""
import asyncio
import logging
from datetime import datetime, timezone

from app.binance_depth import stream_synchronized_depth
from app.config import settings
from app.events import BookTicker
from app.paper import PaperExecutor
from app.portfolio import size_from_free_cash
from app.risk import RiskManager
from app.market_history import MarketHistoryWriter
from app.simulation import ExecutionSimulator
from app.state import RuntimeState
from app.storage import PaperStore
from app.strategy import evaluate_imbalance

log = logging.getLogger(__name__)
state = RuntimeState()
executor = PaperExecutor(settings.starting_cash_usdt, settings.fee_rate)
risk = RiskManager(
    max_order_size_usdt=settings.max_order_size_usdt,
    max_daily_loss_usdt=settings.max_daily_loss_usdt,
    max_consecutive_losses=settings.max_consecutive_losses,
    max_spread_bps=settings.max_spread_bps,
    max_data_age_seconds=settings.max_data_age_seconds,
)
simulator = ExecutionSimulator(
    slippage_bps=settings.simulated_slippage_bps,
    latency_ms=settings.simulated_latency_ms,
    partial_fill_probability=settings.simulated_partial_fill_probability,
    seed=settings.simulation_seed,
)
state.executor, state.risk_manager = executor, risk


def _event_key(key: str, trade: dict) -> str:
    return f"{key}:{trade['timestamp']}:{trade['side']}:{trade['quantity']:.12f}"


async def _simulated_fill(side: str, price: float, quantity: float) -> object:
    fill = simulator.fill(side=side, reference_price=price, quantity=quantity)
    # Latency is deliberately simulated in paper mode; no exchange order is sent.
    if fill.latency_ms:
        await asyncio.sleep(fill.latency_ms / 1000)
    return fill


async def run() -> None:
    store = PaperStore(settings.store_path)
    history = MarketHistoryWriter(settings.market_history_path)
    key = f"paper:{settings.symbol}"
    today = datetime.now(timezone.utc).date().isoformat()
    saved = store.load_state(key)
    if saved:
        executor.restore(saved["account"])
        r = saved.get("risk", {})
        risk.realized_pnl_today = float(r.get("realized_pnl_today", 0))
        risk.consecutive_losses = int(r.get("consecutive_losses", 0))
        risk.kill_switch = bool(r.get("kill_switch", False))
        risk.kill_switch_reason = r.get("kill_switch_reason")
        risk.day_utc = r.get("day_utc")
    risk.rollover_day(today)

    def persist() -> None:
        store.save_state(key, {
            "account": executor.snapshot(),
            "risk": {
                "realized_pnl_today": risk.realized_pnl_today,
                "consecutive_losses": risk.consecutive_losses,
                "kill_switch": risk.kill_switch,
                "kill_switch_reason": risk.kill_switch_reason,
                "day_utc": risk.day_utc,
            },
            "saved_at": datetime.now(timezone.utc).isoformat(),
        })

    confirmations = 0
    try:
        async for depth in stream_synchronized_depth(settings.symbol):
            if not depth.synchronized or not depth.best_bid or not depth.best_ask:
                continue
            bid, bid_qty = depth.best_bid
            ask, ask_qty = depth.best_ask
            # Record the synchronized public L2 state before strategy evaluation.
            # The event is a local observation, not exchange-authoritative history.
            history.append(
                timestamp_ns=__import__("time").time_ns(),
                event_type="depth",
                payload={
                    "symbol": settings.symbol,
                    "best_bid": [bid, bid_qty],
                    "best_ask": [ask, ask_qty],
                    "update_id": getattr(depth, "last_update_id", None),
                    "bids": sorted(getattr(depth, "bids", {}).items(), reverse=True)[:20],
                    "asks": sorted(getattr(depth, "asks", {}).items())[:20],
                },
            )
            if bid <= 0 or ask < bid:
                continue
            risk.rollover_day(datetime.now(timezone.utc).date().isoformat())
            state.update_book(BookTicker(
                settings.symbol, bid, bid_qty, ask, ask_qty, datetime.now(timezone.utc)
            ))

            # TP/SL are paper-only and evaluated only while fresh synchronized data arrives.
            if executor.base_quantity > 0 and executor.average_entry_price > 0:
                move = (bid / executor.average_entry_price - 1) * 100
                reason = (
                    "take_profit" if move >= settings.take_profit_pct
                    else "stop_loss" if move <= -settings.stop_loss_pct
                    else None
                )
                if reason:
                    fill = await _simulated_fill("sell", bid, executor.base_quantity)
                    trade = executor.sell_quantity(
                        quantity=fill.filled_quantity,
                        price=fill.fill_price,
                        reason=f"{reason}; simulated_fill={fill.filled_quantity / fill.requested_quantity:.4f}; slippage_bps={fill.slippage_bps:.3f}; latency_ms={fill.latency_ms}",
                    )
                    if trade:
                        store.append_trade(trade, event_key=_event_key(key, trade))
                        risk.record_realized_pnl(
                            float(trade.get("pnl_usdt", 0)),
                            position_closed=executor.base_quantity <= 0,
                        )
                    persist()
                    continue

            signal = evaluate_imbalance(bid_qty, ask_qty, settings.imbalance_threshold)
            confirmations = confirmations + 1 if signal else 0
            if (
                signal and confirmations >= settings.signal_confirmations
                and executor.base_quantity <= 0 and not risk.kill_switch
            ):
                sizing = size_from_free_cash(
                    free_usdt=executor.cash_usdt,
                    allocation_fraction=0.8,
                    fee_rate=settings.fee_rate,
                    max_order_usdt=min(settings.order_size_usdt, settings.max_order_size_usdt),
                    min_order_usdt=5,
                )
                if sizing.notional_usdt > 0:
                    decision = risk.evaluate_entry(
                        notional_usdt=sizing.notional_usdt,
                        available_cash=executor.cash_usdt,
                        bid=bid,
                        ask=ask,
                        data_age_seconds=state.data_age_seconds(),
                    )
                    if decision.allowed:
                        requested_quantity = sizing.notional_usdt / ask
                        fill = await _simulated_fill("buy", ask, requested_quantity)
                        actual_notional = fill.filled_quantity * fill.fill_price
                        if actual_notional > 0:
                            trade = executor.buy(
                                notional_usdt=actual_notional,
                                price=fill.fill_price,
                                reason=f"{signal.reason}; simulated_fill={fill.filled_quantity / requested_quantity:.4f}; slippage_bps={fill.slippage_bps:.3f}; latency_ms={fill.latency_ms}",
                            )
                            store.append_trade(trade, event_key=_event_key(key, trade))
                        confirmations = 0
            persist()
            await asyncio.sleep(0)
    finally:
        persist()
        store.close()
