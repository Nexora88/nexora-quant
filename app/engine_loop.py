"""Main async depth loop with decision / edge / adverse gates."""
from __future__ import annotations

from datetime import datetime, timezone

from app.config import settings
from app.engine_setup import (
    state, risk, _build_executor, log, executor as _ex,
)
from app.storage import PaperStore
from app.io_queue import AsyncIoQueue
from app.market_history import MarketHistoryWriter
from app.ts_store import FeatureTimeSeriesStore
from app.binance_depth import stream_synchronized_depth
from app.engine_tick import handle_tick
from app.engine_setup import shadows, learner
from app import engine_setup as es


async def run() -> None:
    es.executor = es._build_executor()
    state.executor = es.executor
    store = PaperStore(settings.store_path)
    io_q = AsyncIoQueue(store)
    io_q.start()
    history = MarketHistoryWriter(settings.market_history_path)
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
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        io_q.enqueue_state(key, payload)

    confirmations = 0
    ticks = 0
    try:
        async for depth in stream_synchronized_depth(settings.symbol):
            confirmations, ticks = await handle_tick(
                depth, store, history, features, mode, key, persist, confirmations, ticks,
            )
            await __import__("asyncio").sleep(0)
    finally:
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
