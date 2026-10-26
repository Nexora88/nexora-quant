"""Main async depth loop with decision / edge / adverse gates."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.config import settings
from app.engine_setup import state, risk, log
from app.storage import PaperStore
from app.io_queue import AsyncIoQueue
from app.market_history import MarketHistoryWriter
from app.ts_store import FeatureTimeSeriesStore
from app.binance_depth import stream_synchronized_depth
from app.engine_tick import handle_tick
from app.engine_setup import shadows, learner, memory
from app import engine_setup as es


async def run() -> None:
    es.executor = es._build_executor()
    state.executor = es.executor
    store = PaperStore(settings.store_path)
    io_q = AsyncIoQueue(store)
    io_q.start()
    history = MarketHistoryWriter(
        settings.market_history_path,
        max_pending=int(getattr(settings, "history_max_pending", 4000) or 4000),
    )
    features = FeatureTimeSeriesStore(getattr(settings, "features_db_path", "data/features.sqlite3"))
    mode = settings.trading_mode
    key = f"{mode}:{settings.symbol}"
    today = datetime.now(timezone.utc).date().isoformat()
    saved = store.load_state(key)
    if saved:
        if mode == "paper":
            es.executor.restore(saved["account"])
        else:
            try:
                es.executor.restore(saved["account"])
            except Exception as exc:
                log.warning("Could not restore live local mirror: %s", exc)
        r = saved.get("risk", {})
        risk.realized_pnl_today = float(r.get("realized_pnl_today", 0))
        risk.consecutive_losses = int(r.get("consecutive_losses", 0))
        risk.kill_switch = bool(r.get("kill_switch", False))
        risk.kill_switch_reason = r.get("kill_switch_reason")
        risk.day_utc = r.get("day_utc")
        state.peak_price = float(saved.get("peak_price") or 0)
    risk.rollover_day(today)
    try:
        learner.load_state((saved or {}).get("learner"))
        state.learner_snapshot = learner.to_dict()
        log.info("Learner restored: %s", learner.to_dict().get("note"))
    except Exception as exc:
        log.warning("Learner restore skipped: %s", exc)
    try:
        memory.load_state((saved or {}).get("memory"))
        state.memory_lessons = memory.to_dict()
        log.info("Memory restored: %s", memory.to_dict().get("lifetime_trades"))
    except Exception as exc:
        log.warning("Memory restore skipped: %s", exc)

    log.info(
        "Engine started mode=%s symbol=%s target=%s trailing=%.2f%% score>=%.2f",
        mode,
        settings.symbol.upper(),
        settings.target_price,
        settings.trailing_stop_pct,
        settings.entry_min_score,
    )

    def persist() -> None:
        payload = {
            "account": es.executor.snapshot(),
            "risk": {
                "realized_pnl_today": risk.realized_pnl_today,
                "consecutive_losses": risk.consecutive_losses,
                "kill_switch": risk.kill_switch,
                "kill_switch_reason": risk.kill_switch_reason,
                "day_utc": risk.day_utc,
            },
            "peak_price": state.peak_price,
            "mode": mode,
            "learner": learner.export_state(),
            "memory": memory.export_state(),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        io_q.enqueue_state(key, payload)

    confirmations = 0
    ticks = 0

    async def day_rollover_loop() -> None:
        """Time-driven UTC day reset even when the book is quiet (no WS ticks)."""
        while True:
            try:
                today = datetime.now(timezone.utc).date().isoformat()
                if risk.rollover_day(today):
                    log.info("UTC day rollover → realized_pnl_today reset day=%s", today)
                    persist()
            except Exception:
                log.exception("day_rollover_loop failed")
            await asyncio.sleep(30.0)

    rollover_task = asyncio.create_task(day_rollover_loop(), name="nexora-day-rollover")
    try:
        async for depth in stream_synchronized_depth(settings.symbol):
            confirmations, ticks = await handle_tick(
                depth, store, history, features, mode, key, persist, confirmations, ticks,
            )
            if ticks % 50 == 0:
                try:
                    state.io_queue_stats = io_q.stats()
                    if state.io_queue_stats.get("queue_depth", 0) > state.io_queue_stats.get("queue_max", 1) * 0.7:
                        log.warning("IO queue elevated: %s", state.io_queue_stats)
                except Exception:
                    pass
            await asyncio.sleep(0)
    finally:
        rollover_task.cancel()
        try:
            await rollover_task
        except asyncio.CancelledError:
            pass
        try:
            history.close()
        except Exception:
            pass
        persist()
        await io_q.stop()
        store.close()
        try:
            features.close()
        except Exception:
            pass
        try:
            board = shadows.leaderboard()
            state.shadow_leaderboard = board
            log.info("Shadow leaderboard: %s", board[:3])
        except Exception:
            pass
