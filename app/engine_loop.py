"""Main async depth loop with decision / edge / adverse gates."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from app.config import settings
from app.engine_setup import state, risk, log
from app.storage import PaperStore
from app.io_queue import AsyncIoQueue
from app.market_history import MarketHistoryWriter
from app.ts_store import FeatureTimeSeriesStore
from app.binance_depth import stream_synchronized_depth
from app.multi_stream import stream_multi_depth, watch_list
from app.universe import screen_universe, depth_watch_from_screen, default_universe
try:
    from app._apply_antichurn_once import apply as _apply_antichurn
    _apply_antichurn()
except Exception:
    pass
from app.engine_tick import handle_tick
from app.engine_setup import shadows, learner, memory, motor
from app import engine_setup as es


async def run() -> None:
    es.executor = es._build_executor()
    state.executor = es.executor
    store = PaperStore(settings.store_path)
    io_q = AsyncIoQueue(store)
    io_q.start()
    hist_on = bool(getattr(settings, "market_history_enabled", False))
    history = MarketHistoryWriter(
        settings.market_history_path,
        max_pending=int(getattr(settings, "history_max_pending", 4000) or 4000),
        enabled=hist_on,
    )
    if not hist_on:
        log.info("Market history disabled (set MARKET_HISTORY_ENABLED=true to record L2)")
    features = FeatureTimeSeriesStore(getattr(settings, "features_db_path", "data/features.sqlite3"))
    mode = settings.trading_mode
    key = f"{mode}:{settings.symbol}"
    today = datetime.now(timezone.utc).date().isoformat()
    saved = store.load_state(key)
    if saved:
        if mode == "paper":
            es.executor.restore(saved["account"])
            target_cash = float(settings.starting_cash_usdt)
            bq = float(getattr(es.executor, "base_quantity", 0) or 0)
            ep = float(getattr(es.executor, "average_entry_price", 0) or 0)
            notional = bq * ep if bq > 0 and ep > 0 else 0.0
            min_n = float(getattr(settings, "min_order_usdt", 6.0) or 6.0)
            if bq > 0 and (notional < min_n or bq < 1e-10 or ep <= 0):
                log.warning(
                    "Clearing dust/zombie paper position qty=%.8f notional=%.4f",
                    bq,
                    notional,
                )
                es.executor.base_quantity = 0.0
                es.executor.average_entry_price = 0.0
            elif abs(float(es.executor.starting_cash_usdt) - target_cash) > 0.01 and bq <= 0:
                log.info(
                    "Paper starting cash %.2f -> %.2f (flat)",
                    es.executor.starting_cash_usdt,
                    target_cash,
                )
                es.executor.starting_cash_usdt = target_cash
                es.executor.cash_usdt = target_cash
        else:
            es.executor.restore(saved["account"])
        risk.restore(saved.get("risk") or {})
    risk.roll_day(today)

    def persist() -> None:
        try:
            store.save_state(
                key,
                {
                    "account": es.executor.snapshot(
                        state.latest_book.bid if state.latest_book else None
                    ),
                    "risk": risk.snapshot(),
                },
            )
        except Exception:
            log.exception("persist failed")

    primary = settings.symbol.lower()
    symbols = [primary]
    if getattr(settings, "universe_auto", False):
        try:
            board = screen_universe()
            state.universe_board = board
            watch = depth_watch_from_screen(board)
            if primary not in watch:
                watch = [primary] + watch
            symbols = watch[: int(getattr(settings, "max_depth_symbols", 6) or 6)]
            state.depth_watch = symbols
        except Exception:
            log.exception("universe screen failed")
            symbols = default_universe()

    ticks = 0
    confirmations = 0
    reconnect = 0

    async def _consume(book, *, symbol: str) -> None:
        nonlocal ticks, confirmations, primary
        sym = (symbol or primary).lower()
        if sym != primary:
            bq = float(getattr(es.executor, "base_quantity", 0) or 0)
            if bq > 0:
                return
            primary = sym
            state.trade_symbol = primary
            log.info("primary switch (flat) -> %s", primary)
        ticks, confirmations = await handle_tick(
            book,
            ticks=ticks,
            confirmations=confirmations,
            mode=mode,
            key=key,
            store=store,
            io_q=io_q,
            history=history,
            features=features,
            primary=primary,
        )

    while True:
        try:
            if len(symbols) <= 1:
                async for book in stream_synchronized_depth(symbols[0]):
                    await _consume(book, symbol=symbols[0])
            else:
                async for tagged in stream_multi_depth(symbols):
                    await _consume(tagged.book, symbol=tagged.symbol)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reconnect += 1
            state.reconnect_count = reconnect
            state.last_error = str(exc)[:200]
            log.exception("L2 stream error; reconnect #%s in 2s: %s", reconnect, exc)
            await asyncio.sleep(2.0)
