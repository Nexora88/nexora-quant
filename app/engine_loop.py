"""Main async depth loop with decision / edge / adverse gates."""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import datetime, timezone

from app.config import settings
from app.engine_setup import state, risk, log
from app.storage import PaperStore
from app.dual_account import ReconciliationMonitor
from app.paper import restore_paper_account
from app.io_queue import AsyncIoQueue
from app.market_history import MarketHistoryWriter
from app.ts_store import FeatureTimeSeriesStore
from app.binance_depth import stream_synchronized_depth
from app.binance_ws import stream_events
from app.events import TradeTick, KlineTick
from app.trade_flow import TradeFlowTracker
from app.market_indicators import Candle, MarketIndicatorTracker, fetch_recent_candles
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

    def reconcile_live_startup() -> None:
        es.executor.sync_balances()
        if (
            float(getattr(es.executor, "base_quantity", 0) or 0) > 1e-12
            and getattr(es.executor, "protective_order_list_id", None) is None
        ):
            # A restored live position without exchange-hosted protection is not
            # allowed to run naked after a process restart.
            current_price = float(es.executor.client.ticker_price(es.executor.symbol))
            take_profit = float(
                (saved or {}).get("position_tp_pct") or settings.take_profit_pct
            )
            stop_loss = float(
                (saved or {}).get("position_sl_pct") or settings.stop_loss_pct
            )
            if not es.executor.install_protection_or_flatten(
                current_price=current_price,
                take_profit_pct=take_profit,
                stop_loss_pct=stop_loss,
                mark_price=current_price,
            ):
                risk.activate_kill_switch("Could not restore exchange-hosted position protection")
                raise RuntimeError("Live position protection could not be restored; refusing to start")

    if saved:
        if mode == "paper":
            resume = os.getenv("PAPER_RESUME_POSITION", "true").strip().lower() in {
                "1", "true", "yes", "on",
            }
            has_position = restore_paper_account(
                es.executor, saved["account"], resume_position=resume,
            )
            bq = float(es.executor.base_quantity)
            ep = float(es.executor.average_entry_price)
            notional = bq * ep if bq > 0 and ep > 0 else 0.0
            min_n = float(getattr(settings, "min_order_usdt", 6.0) or 6.0)
            if has_position and notional < min_n:
                log.warning(
                    "Restored paper dust position retained qty=%.8f notional=%.4f",
                    bq, notional,
                )
            target_cash = float(settings.starting_cash_usdt)
            if abs(float(es.executor.starting_cash_usdt) - target_cash) > 1e-6:
                log.warning(
                    "STARTING_CASH_USDT=%.2f differs from saved bankroll %.2f; preserving saved account",
                    target_cash, es.executor.starting_cash_usdt,
                )
        else:
            if saved:
                try:
                    es.executor.restore(saved["account"])
                except Exception as exc:
                    risk.activate_kill_switch("Live local ledger restore failed")
                    state.last_error = "live_ledger_restore_failed"
                    raise RuntimeError("Live local ledger restore failed; refusing to start") from exc
            try:
                # Reconcile balances, OCO history, and restore missing protection
                # before the engine can submit or manage any live order.
                reconcile_live_startup()
            except Exception as exc:
                risk.activate_kill_switch("Live exchange startup reconciliation failed")
                state.last_error = "live_startup_reconciliation_failed"
                log.exception("Live startup reconciliation failed; engine will not trade")
                raise RuntimeError("Live startup reconciliation failed; refusing to start") from exc
        risk.restore(saved.get("risk") or {})
        state.restore_evidence(saved.get("evidence") or {})
        if mode == "paper" and risk.kill_switch:
            # Paper mode must not silently resume entries after a loss-streak halt.
            # Require an explicit operator reset after reviewing the paper ledger.
            log.warning("Preserving restored paper kill_switch: %s", risk.kill_switch_reason)
        state.peak_price = float(saved.get("peak_price") or 0)
        restored_symbol = settings.symbol.lower()
        if mode == "paper" and float(getattr(es.executor, "base_quantity", 0) or 0) > 1e-12:
            restored_symbol = str(saved.get("trade_symbol") or settings.symbol).lower()
        if not restored_symbol.isalnum():
            raise RuntimeError("Saved trade symbol is invalid; refusing to restore position")
        state.trade_symbol = restored_symbol
        state.position_opened_at = saved.get("position_opened_at")
        state.position_tp_pct = saved.get("position_tp_pct")
        state.position_sl_pct = saved.get("position_sl_pct")
        state.position_trail_pct = saved.get("position_trail_pct")
        state.last_entry_at = saved.get("last_entry_at")
        state.hourly_trade_ts = [
            float(value) for value in (saved.get("hourly_trade_ts") or [])
            if isinstance(value, (int, float))
        ]
        from app.atr_stops import WickStopState
        state.wick_stop_state = WickStopState(
            below_count=max(0, int(saved.get("wick_stop_below_count", 0) or 0))
        )
        if (
            mode == "paper"
            and float(getattr(es.executor, "base_quantity", 0) or 0) > 1e-12
            and not state.position_opened_at
        ):
            state.position_opened_at = time.time() - float(
                getattr(settings, "max_hold_seconds", 2700.0) or 2700.0
            )
            log.warning("Legacy paper position has no open timestamp; forcing time-stop on first fresh tick")
    if mode == "live" and not saved:
        try:
            reconcile_live_startup()
        except Exception as exc:
            risk.activate_kill_switch("Live exchange startup reconciliation failed")
            state.last_error = "live_startup_reconciliation_failed"
            log.exception("Live startup reconciliation failed; engine will not trade")
            raise RuntimeError("Live startup reconciliation failed; refusing to start") from exc
    if risk.rollover_day(today):
        state.session_fees_usdt = 0.0
        state.session_fee_day = today
    try:
        learner.load_state((saved or {}).get("learner"))
        state.learner_snapshot = learner.to_dict()
        # Prefer the account-scoped learner state; it cannot cross paper/live accounts.
        es.account_learning.restore()
        # A live account may load only an explicitly promoted, paper-origin strategy.
        if mode == "live":
            promoted = es.dual_account_store.active_strategy(es.account_id)
            if promoted:
                weights = learner.export_state()
                params = promoted["parameters"]
                mapping = {
                    "entry_min_score": "entry_min",
                    "size_bias": "size_bias",
                    "tp_scale": "tp_scale",
                    "compound_fraction": "compound",
                }
                for source, target in mapping.items():
                    if source in params:
                        weights[target] = float(params[source])
                learner.load_state(weights)
                log.info("Loaded approved strategy version=%s", promoted["version_id"])
        state.learner_snapshot = learner.to_dict()
        log.info("Learner restored: %s", learner.to_dict().get("note"))
    except Exception as exc:
        log.warning("Learner restore skipped: %s", exc)
    try:
        motor.load_state((saved or {}).get("motor"))
        log.info(
            "Motor restored bias=%s ema=%.3f",
            getattr(motor, "_bias", "?"),
            getattr(motor, "_ema_fused", 0.0),
        )
    except Exception as exc:
        log.warning("Motor restore skipped: %s", exc)
    try:
        memory.load_state((saved or {}).get("memory"))
        state.memory_lessons = memory.to_dict()
        log.info("Memory restored: %s", memory.to_dict().get("lifetime_trades"))
    except Exception as exc:
        log.warning("Memory restore skipped: %s", exc)

    watched = watch_list(settings.symbol, settings.watch_symbols())
    if getattr(settings, "universe_auto", False):
        try:
            screened = screen_universe(
                candidates=default_universe(),
                top_n=int(getattr(settings, "depth_top_n", 5) or 5),
                min_quote_volume=float(getattr(settings, "universe_min_quote_volume", 5_000_000) or 5e6),
            )
            state.universe_board = [r.to_dict() for r in screened]
            depth_syms = depth_watch_from_screen(
                screened, max_depth=int(getattr(settings, "depth_top_n", 5) or 5),
            )
            for s in settings.watch_symbols():
                if s not in depth_syms:
                    depth_syms.append(s)
            watched = watch_list(settings.symbol, tuple(depth_syms))
            cap = max(3, min(8, int(getattr(settings, "depth_top_n", 5) or 5) + 1))
            watched = watched[:cap]
            if "btcusdt" not in watched:
                watched.append("btcusdt")
            state.depth_watch = list(watched)
            log.info(
                "Universe screen → depth watch %s (from %d majors)",
                ",".join(s.upper() for s in watched),
                len(default_universe()),
            )
        except Exception as exc:
            log.warning("Universe screen failed, fallback watch_list: %s", exc)
            state.universe_board = []
            state.depth_watch = list(watched)
    else:
        state.universe_board = []
        state.depth_watch = list(watched)
    if mode == "paper" and float(getattr(es.executor, "base_quantity", 0) or 0) > 1e-12:
        restored_symbol = str(state.trade_symbol or settings.symbol).lower()
        if restored_symbol not in watched:
            watched = [restored_symbol] + [symbol for symbol in watched if symbol != restored_symbol]
            watched = watched[:8]
            state.depth_watch = list(watched)
    log.info(
        "Bankroll mode=%s starting_cash=%.2f order_size=%.2f max_order=%.2f",
        mode,
        settings.starting_cash_usdt,
        settings.order_size_usdt,
        settings.max_order_size_usdt,
    )
    log.info(
        "Engine started mode=%s primary=%s watch=%s autonomous_symbol=%s trailing=%.2f%% score>=%.2f",
        mode,
        settings.symbol.upper(),
        ",".join(s.upper() for s in watched),
        getattr(settings, "autonomous_symbol", False),
        settings.trailing_stop_pct,
        settings.entry_min_score,
    )

    def persist() -> None:
        payload = {
            "account": es.executor.snapshot(),
            "risk": risk.snapshot(),
            "evidence": state.evidence_snapshot(),
            "peak_price": state.peak_price,
            "trade_symbol": state.trade_symbol or settings.symbol.lower(),
            "position_opened_at": state.position_opened_at,
            "position_tp_pct": state.position_tp_pct,
            "position_sl_pct": state.position_sl_pct,
            "position_trail_pct": state.position_trail_pct,
            "last_entry_at": state.last_entry_at,
            "hourly_trade_ts": list(state.hourly_trade_ts),
            "wick_stop_below_count": int(getattr(state.wick_stop_state, "below_count", 0) or 0),
            "mode": mode,
            "learner": learner.export_state(),
            "memory": memory.export_state(),
            "motor": motor.export_state(),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        io_q.enqueue_state(key, payload)

    confirmations = 0
    ticks = 0

    async def day_rollover_loop() -> None:
        while True:
            try:
                today = datetime.now(timezone.utc).date().isoformat()
                if risk.rollover_day(today):
                    state.session_fees_usdt = 0.0
                    state.session_fee_day = today
                    log.info("UTC day rollover -> daily risk counters reset day=%s", today)
                    persist()
                store.heartbeat_session(
                    session_id, ticks=ticks, reconnects=state.reconnect_count,
                    trade_count=len(getattr(es.executor, "trades", []) or []),
                    realized_pnl_usdt=float(getattr(es.executor, "realized_pnl_usdt", 0.0) or 0.0),
                )
            except Exception:
                log.exception("day_rollover_loop failed")
            await asyncio.sleep(30.0)

    session_id = uuid.uuid4().hex
    store.start_session(session_id, mode)
    rollover_task = asyncio.create_task(day_rollover_loop(), name="nexora-day-rollover")

    def on_depth_reconnect(symbol: str, exc: Exception) -> None:
        state.reconnect_count += 1
        state.last_error = f"depth_reconnect:{symbol}:{type(exc).__name__}"
        log.warning("Depth resynchronization symbol=%s reconnect_count=%s", symbol, state.reconnect_count)

    primary = (
        str(state.trade_symbol or settings.symbol).lower()
        if mode == "paper" and float(getattr(es.executor, "base_quantity", 0) or 0) > 1e-12
        else settings.symbol.lower()
    )
    trade_tasks: list[asyncio.Task] = []

    if mode == "live":
        async def _exchange_reconciliation_snapshot():
            def _read_snapshots():
                client = es.executor.client
                account_payload = client.account()
                balances = {
                    str(item.get("asset", "")).upper(): item
                    for item in account_payload.get("balances", [])
                }
                quote = balances.get(str(es.executor.quote_asset).upper(), {})
                base = balances.get(str(es.executor.base_asset).upper(), {})
                local_snapshot = {
                    "cash_usdt": float(es.executor.cash_usdt),
                    "base_quantity": float(es.executor.base_quantity),
                    "open_order_count": (
                        1 if getattr(es.executor, "protective_order_list_id", None) is not None else 0
                    ),
                }
                exchange_snapshot = {
                    "cash_usdt": float(quote.get("free", 0.0)),
                    "base_quantity": float(base.get("free", 0.0)) + float(base.get("locked", 0.0)),
                    "open_order_count": len(client.open_order_lists()),
                }
                return local_snapshot, exchange_snapshot

            return await asyncio.to_thread(_read_snapshots)

        def _reconciliation_mismatch(result: dict) -> None:
            risk.activate_kill_switch("Recurring exchange/local account reconciliation failed")
            state.last_error = "exchange_local_reconciliation_mismatch"
            log.error("Live account reconciliation failed: %s", result)
            persist()

        monitor = ReconciliationMonitor(
            es.dual_account_store,
            es.account_id,
            _exchange_reconciliation_snapshot,
            _reconciliation_mismatch,
            interval_seconds=float(os.getenv("RECONCILIATION_INTERVAL_SECONDS", "30")),
        )
        trade_tasks.append(
            asyncio.create_task(monitor.run_forever(), name="live-account-reconciliation")
        )

    async def _trade_pump(symbol: str) -> None:
        tracker = TradeFlowTracker(window_seconds=10.0, min_trades=20, max_age_seconds=2.5)
        indicators = MarketIndicatorTracker()
        trackers = getattr(state, "trade_flow_trackers", None)
        if trackers is None:
            trackers = {}
            state.trade_flow_trackers = trackers
        indicator_trackers = getattr(state, "market_indicator_trackers", None)
        if indicator_trackers is None:
            indicator_trackers = {}
            state.market_indicator_trackers = indicator_trackers
        trackers[symbol] = tracker
        indicator_trackers[symbol] = indicators
        # Seed EMA200/RSI/MACD and 5m context from closed public candles.
        try:
            one_minute, five_minute = await asyncio.gather(
                asyncio.to_thread(fetch_recent_candles, symbol, "1m", limit=250),
                asyncio.to_thread(fetch_recent_candles, symbol, "5m", limit=100),
            )
            indicators.seed(one_minute + five_minute)
            log.info(
                "Indicator warm-up symbol=%s 1m=%s 5m=%s",
                symbol.upper(), len(one_minute), len(five_minute),
            )
        except Exception as exc:
            log.warning("Indicator history unavailable symbol=%s: %s; entries remain gated", symbol.upper(), exc)
        while True:
            try:
                async for event in stream_events(symbol):
                    if isinstance(event, TradeTick):
                        tracker.update(event)
                    elif isinstance(event, KlineTick) and event.closed:
                        indicators.update(Candle(
                            symbol=event.symbol, interval=event.interval,
                            open_time=event.open_time, open=event.open, high=event.high,
                            low=event.low, close=event.close, volume=event.volume,
                            closed=True, received_at=event.received_at.timestamp(),
                        ))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state.last_error = f"trade_stream:{symbol}:{type(exc).__name__}"
                log.exception("Trade stream failed symbol=%s", symbol)
                await asyncio.sleep(1.0)

    trade_watch = list(dict.fromkeys([*watched, "btcusdt", "ethusdt"]))
    for trade_symbol in trade_watch:
        trade_tasks.append(asyncio.create_task(_trade_pump(trade_symbol), name=f"trades-{trade_symbol}"))

    try:
        # A fixed SYMBOLS list must also start every configured depth stream.
        # UNIVERSE_AUTO controls dynamic discovery, not manual watchlist subscriptions.
        # Otherwise a 9-symbol paper profile silently scans only its primary symbol.
        use_multi = len(watched) > 1

        async def _consume(depth, *, symbol: str | None = None) -> None:
            nonlocal confirmations, ticks, primary
            sym = (symbol or primary).lower()
            if sym != primary:
                try:
                    if depth.synchronized and depth.best_bid and depth.best_ask:
                        board = getattr(state, "side_books", None) or {}
                        bid, bq = depth.best_bid
                        ask, aq = depth.best_ask
                        mid = (ask + bid) / 2.0 if ask + bid else 0.0
                        spread_bps = ((ask - bid) / mid * 10_000) if mid else 0.0
                        board[sym] = {
                            "bid": bid,
                            "ask": ask,
                            "bid_qty": bq,
                            "ask_qty": aq,
                            "spread_bps": spread_bps,
                            "mid": mid,
                            "updated_at": time.time(),
                        }
                        state.side_books = board
                        imb = (bq / (bq + aq)) if (bq + aq) > 0 else 0.5
                        rough = max(0.0, min(1.0, 0.45 + (imb - 0.5) * 1.2 - min(spread_bps, 25) / 80.0))
                        es.symbol_router.update(
                            sym,
                            score=rough,
                            regime="scan",
                            depth_usdt=mid * min(bq, aq) * 2.0 if mid else 0.0,
                            liquid=spread_bps < 25.0,
                            reasons=[f"scan_obi={imb:.2f}"],
                        )
                        state.router_board = es.symbol_router.leaderboard()
                        if (
                            mode == "paper"
                            and bool(getattr(settings, "autonomous_symbol", True))
                            and es.executor is not None
                            and float(getattr(es.executor, "base_quantity", 0) or 0) <= 0
                        ):
                            best = es.symbol_router.select_best()
                            if best and best.symbol != primary and best.score >= float(settings.entry_min_score):
                                primary = best.symbol
                                state.trade_symbol = primary
                                log.info("Router switch → %s score=%.2f", primary.upper(), best.score)
                except Exception:
                    log.exception("side-book/router update failed for %s", sym)
                return
            confirmations, ticks = await handle_tick(
                depth, store, history, features, mode, key, persist, confirmations, ticks,
            )
            if ticks == 1 or ticks % 200 == 0:
                log.info(
                    "L2 live primary=%s ticks=%s mid_ok=%s",
                    primary.upper(),
                    ticks,
                    bool(depth.synchronized and depth.best_bid),
                )
            if ticks % 50 == 0:
                try:
                    state.io_queue_stats = io_q.stats()
                    if state.io_queue_stats.get("queue_depth", 0) > state.io_queue_stats.get("queue_max", 1) * 0.7:
                        log.warning("IO queue elevated: %s", state.io_queue_stats)
                except Exception:
                    pass
            await asyncio.sleep(0)

        while True:
            try:
                if use_multi:
                    log.info("Starting multi-depth (primary trades only): %s", ",".join(watched))
                    async for tagged in stream_multi_depth(watched, on_reconnect=on_depth_reconnect):
                        tagged.book.symbol = tagged.symbol
                        await _consume(tagged.book, symbol=tagged.symbol)
                else:
                    log.info("Starting single-depth L2: %s", primary.upper())
                    async for depth in stream_synchronized_depth(
                        primary, on_reconnect=on_depth_reconnect,
                    ):
                        depth.symbol = primary
                        await _consume(depth, symbol=primary)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state.reconnect_count = int(getattr(state, "reconnect_count", 0) or 0) + 1
                state.last_error = f"l2_reconnect:{type(exc).__name__}"
                log.exception(
                    "L2 stream error; reconnect #%s in 2s: %s",
                    state.reconnect_count,
                    exc,
                )
                await asyncio.sleep(2.0)
    finally:
        for task in trade_tasks:
            task.cancel()
        if trade_tasks:
            await asyncio.gather(*trade_tasks, return_exceptions=True)
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
        try:
            store.end_session(
                session_id, ticks=ticks, reconnects=state.reconnect_count,
                trade_count=len(getattr(es.executor, "trades", []) or []),
                realized_pnl_usdt=float(getattr(es.executor, "realized_pnl_usdt", 0.0) or 0.0),
            )
        except Exception:
            log.exception("Could not finalize paper session telemetry")
        try:
            store.close()
        except Exception:
            log.exception("PaperStore close failed; durable ledger flush is incomplete")
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
