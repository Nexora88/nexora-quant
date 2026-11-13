"""Per-depth-tick: microstructure analysis, decision, edge, adverse, paper/live fills."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from app import engine_setup as es
from app.config import settings
from app.decision import build_decision
from app.engine_setup import (
    _event_key,
    _paper_fill,
    adverse_filter,
    atr_tracker,
    circuit_breaker,
    kelly,
    learner,
    log,
    order_flow,
    ou_tracker,
    portfolio_risk,
    price_window,
    regime_clf,
    risk,
    shadows,
    state,
    sustained,
    wall_tracker,
    whale_tracker,
)
from app.events import BookTicker
from app.portfolio import size_from_free_cash
from app.atr_stops import compute_dynamic_targets, WickStopState
from app.autonomous_policy import regime_targets, vol_adjusted_notional, impact_capped_notional, assess_liquidity
from app.simulation import market_impact_bps
from app.strategy import analyze_market, entry_signal_from_analysis, exit_reason


async def handle_tick(
    depth,
    store,
    history,
    features,
    mode: str,
    key: str,
    persist,
    confirmations: int,
    ticks: int,
) -> tuple[int, int]:
    if not depth.synchronized or not depth.best_bid or not depth.best_ask:
        return confirmations, ticks
    if getattr(state, "paused", False):
        return confirmations, ticks
    bid, bid_qty = depth.best_bid
    ask, ask_qty = depth.best_ask
    history.append(
        timestamp_ns=time.time_ns(),
        event_type="depth",
        payload={
            "symbol": (getattr(state, "trade_symbol", None) or settings.symbol),
            "best_bid": [bid, bid_qty],
            "best_ask": [ask, ask_qty],
            "update_id": getattr(depth, "last_update_id", None),
            "bids": sorted(getattr(depth, "bids", {}).items(), reverse=True)[:20],
            "asks": sorted(getattr(depth, "asks", {}).items())[:20],
        },
    )
    if bid <= 0 or ask < bid:
        return confirmations, ticks
    trade_sym = (getattr(state, "trade_symbol", None) or settings.symbol).lower()
    risk.rollover_day(datetime.now(timezone.utc).date().isoformat())
    state.update_book(
        BookTicker(trade_sym, bid, bid_qty, ask, ask_qty, datetime.now(timezone.utc))
    )

    depth_bids = sorted(getattr(depth, "bids", {}).items(), reverse=True)[:15] or [(bid, bid_qty)]
    depth_asks = sorted(getattr(depth, "asks", {}).items())[:15] or [(ask, ask_qty)]
    wall_tracker.update(depth_bids, depth_asks)
    analysis = analyze_market(
        bid=bid, ask=ask, bid_qty=bid_qty, ask_qty=ask_qty,
        price_window=price_window, imbalance_threshold=settings.imbalance_threshold,
        target_price=settings.target_price, bids=depth_bids, asks=depth_asks,
        ou=ou_tracker, regime_classifier=regime_clf, wall_bias=wall_tracker.bias(),
    )
    whale = whale_tracker.update(depth_bids, depth_asks, analysis.mid)
    try:
        shadows.on_tick(
            score=analysis.score, bid=bid, ask=ask, size_usdt=settings.order_size_usdt,
            fee=settings.fee_rate, stop_pct=settings.stop_loss_pct, tp_pct=settings.take_profit_pct,
        )
        state.shadow_leaderboard = shadows.leaderboard(bid)
    except Exception:
        pass
    state.record_analysis(analysis)
    flow = order_flow.update(
        imbalance=float(analysis.imbalance or 0.5),
        micro_premium_bps=float(getattr(analysis, "micro_premium_bps", 0.0) or 0.0),
    )
    try:
        state.last_flow = {"pressure": flow.pressure, "ready": flow.ready, "note": flow.note, "samples": flow.samples}
    except Exception:
        pass
    atr_now = atr_tracker.update(analysis.mid) if analysis.mid and analysis.mid > 0 else float(atr_tracker.atr_pct or 0.0)
    now_ms = int(time.time() * 1000)
    if hasattr(es, "execution_costs"):
        es.execution_costs.observe_mid(analysis.mid, now_ms)
    try:
        features.append(
            ts_ns=time.time_ns(), symbol=trade_sym, mid=analysis.mid,
            spread_bps=analysis.spread_bps, imbalance=analysis.imbalance,
            momentum_bps=analysis.momentum_bps, score=analysis.score, bid=bid, ask=ask,
            extra={
                "trend": analysis.trend, "reasons": analysis.reasons[:5],
                "regime": analysis.regime, "weighted_obi": analysis.weighted_obi,
                "micro_premium_bps": analysis.micro_premium_bps, "ou_zscore": analysis.ou_zscore,
            },
        )
    except Exception:
        log.debug("feature append failed", exc_info=True)

    ticks += 1
    if ticks % 15 == 0:
        state.sample_equity()

    ex = es.executor
    if ex and ex.base_quantity > 0 and ex.average_entry_price > 0:
        if state.peak_price <= 0:
            state.peak_price = bid
        else:
            state.peak_price = max(float(state.peak_price), bid)

        if getattr(state, "wick_stop_state", None) is None:
            state.wick_stop_state = WickStopState()

        reason = exit_reason(
            bid=bid, average_entry=ex.average_entry_price,
            take_profit_pct=float(state.position_tp_pct or settings.take_profit_pct),
            stop_loss_pct=float(state.position_sl_pct or settings.stop_loss_pct),
            trailing_stop_pct=float(state.position_trail_pct or settings.trailing_stop_pct),
            peak_price=state.peak_price,
            target_price=settings.target_price,
            wick_confirmations=int(getattr(settings, "wick_stop_confirmations", 0) or 0),
            wick_state=state.wick_stop_state,
        )

        opened = getattr(state, "position_opened_at", None)
        held = (time.time() - float(opened)) if opened else 0.0
        max_hold = float(getattr(settings, "max_hold_seconds", 2700.0) or 0.0)
        if not reason and max_hold > 0 and opened and held >= max_hold:
            reason = "time_stop"

        if reason and reason not in ("stop_loss", "trailing_stop", "emergency", "kill", "time_stop"):
            min_hold = float(getattr(settings, "min_hold_seconds", 90.0) or 0.0)
            if min_hold > 0 and opened and held < min_hold:
                reason = None
                if ticks % 40 == 0:
                    log.info("min_hold gate: held=%.0fs need=%.0fs", held, min_hold)

        if ticks % 60 == 0:
            move_pct = (bid / ex.average_entry_price - 1.0) * 100.0
            log.info(
                "in_pos held=%.0fs move=%.3f%% peak=%.2f tp=%.2f sl=%.2f trail=%.2f reason=%s",
                held, move_pct, state.peak_price,
                float(state.position_tp_pct or settings.take_profit_pct),
                float(state.position_sl_pct or settings.stop_loss_pct),
                float(state.position_trail_pct or settings.trailing_stop_pct),
                reason or "-",
            )

        if reason:
            try:
                if mode == "paper":
                    stress = reason in ("stop_loss", "trailing_stop", "time_stop")
                    fill = await _paper_fill(
                        "sell", bid, ex.base_quantity, book_levels=depth_bids, stress=stress,
                    )
                    trade = ex.sell_quantity(
                        quantity=fill.filled_quantity, price=fill.fill_price,
                        reason=(
                            f"{reason}; sim_fill={fill.filled_quantity / fill.requested_quantity:.4f}"
                            f"; slip_bps={fill.slippage_bps:.1f}"
                            f"{';stress' if getattr(fill, 'stress_applied', False) else ''}"
                        ),
                    )
                else:
                    if getattr(ex, "protective_order_list_id", None) is not None:
                        if not ex.cancel_protective_oco():
                            risk.activate_kill_switch("Could not safely cancel/reconcile protective OCO")
                            state.last_error = "protective_oco_reconciliation_failed"
                            persist()
                            return confirmations, ticks
                    if ex.base_quantity <= 0:
                        risk.activate_kill_switch("Position changed on exchange; reconcile fills")
                        state.last_error = "exchange_position_changed_requires_reconciliation"
                        persist()
                        return confirmations, ticks
                    trade = ex.sell_quantity(
                        quantity=ex.base_quantity, price=bid,
                        reason=f"{reason}; live_market_sell", decision_mid=analysis.mid,
                    )
                if trade:
                    if not trade.get("accounting_complete", True):
                        risk.activate_kill_switch("Exchange commission accounting incomplete")
                        state.last_error = "commission_accounting_incomplete"
                    if (
                        mode == "live" and trade.get("decision_mid")
                        and trade.get("execution_latency_measured", False)
                        and hasattr(es, "execution_costs")
                    ):
                        es.execution_costs.record_fill(
                            side=trade["side"], decision_mid=float(trade["decision_mid"]),
                            fill_price=float(trade["price"]),
                            latency_ms=float(trade["execution_latency_ms"]),
                            filled_at_ms=int(time.time() * 1000),
                        )
                    store.append_trade(trade, event_key=_event_key(key, trade))
                    state.record_fill(trade)
                    pnl_v = float(trade.get("pnl_usdt", 0))
                    risk.record_realized_pnl(pnl_v, position_closed=ex.base_quantity <= 0)
                    try:
                        kelly.record_pnl(pnl_v)
                    except Exception:
                        pass
                    if ex.base_quantity <= 0:
                        state.peak_price = 0.0
                        try:
                            portfolio_risk.unregister(settings.symbol)
                        except Exception:
                            pass
                        state.position_tp_pct = None
                        state.position_sl_pct = None
                        state.position_trail_pct = None
                        state.position_opened_at = None
                        state.wick_stop_state = None
                        try:
                            learner.record_trade(
                                float(pnl_v),
                                regime=str(getattr(analysis, "regime", "unknown") or "unknown"),
                                reason=str(reason or ""),
                            )
                            state.learner_snapshot = (
                                learner.snapshot() if hasattr(learner, "snapshot") else learner.to_dict()
                            )
                        except Exception:
                            log.exception("learner.record_trade failed")
                        try:
                            circuit_breaker.record_closed_pnl(float(pnl_v))
                        except Exception:
                            log.exception("circuit_breaker.record_closed_pnl failed")
            except Exception:
                log.exception("Exit order failed (%s)", reason)
                state.last_error = f"exit_failed:{reason}"
                if getattr(ex, "order_state_uncertain", False):
                    risk.activate_kill_switch("Exchange order outcome uncertain")
            persist()
            return confirmations, ticks

    try:
        cb_min = float(circuit_breaker.effective_min_score(settings.entry_min_score))
        cb_allow = bool(circuit_breaker.allow_entry())
    except Exception:
        cb_min = float(settings.entry_min_score)
        cb_allow = True
    effective_min_score = max(float(settings.entry_min_score), cb_min)

    signal = entry_signal_from_analysis(analysis, min_score=effective_min_score)
    state.record_signal(signal)
    sus = sustained.update(analysis.score if analysis.score >= effective_min_score else 0.0)
    confirmations = sus.consecutive
    free = getattr(ex, "cash_usdt", settings.starting_cash_usdt) if ex else settings.starting_cash_usdt
    kd_preview = kelly.size(free_usdt=free, fee_rate=settings.effective_fee_rate())
    adverse_filter.update(mid=analysis.mid, spread_bps=analysis.spread_bps, micro_price=analysis.micro_price)
    auto_mode = bool(getattr(settings, "autonomous_mode", True))
    _pre = build_decision(
        analysis=analysis, sustained=sus, in_position=bool(ex and ex.base_quantity > 0),
        kill_switch=bool(risk.kill_switch), kill_reason=risk.kill_switch_reason,
        kelly_fraction=kd_preview.fraction, suggested_notional=kd_preview.notional_usdt,
        entry_min_score=effective_min_score,
        autonomous_mode=auto_mode,
    )
    impact_est = market_impact_bps(
        notional_usdt=kd_preview.notional_usdt or settings.order_size_usdt,
        visible_liquidity_usdt=max(ask * max(ask_qty, 1e-9), 1.0),
        coefficient=getattr(settings, "impact_coefficient", 0.1),
    )
    estimated_latency_ms = (
        es.execution_costs.estimate_latency_ms() if mode == "live" and hasattr(es, "execution_costs") else None
    )
    calibrated_latency_cost = (
        es.execution_costs.estimate_cost_bps(latency_ms=estimated_latency_ms)
        if mode == "live" and estimated_latency_ms is not None and hasattr(es, "execution_costs") else None
    )
    try:
        from app.intelligence.edge import score_edge_for_desk
        atr_now = float(getattr(atr_tracker, "atr_pct", 0.0) or 0.0)
        soft = mode == "paper" and bool(getattr(settings, "paper_soft_gates", True))
        rt_impact = max(0.0, 2.0 * float(impact_est or 0.0))
        rt_fee_bps = max(0.0, 2.0 * float(settings.effective_fee_rate()) * 10_000)
        if mode == "paper":
            paper_latency_buffer_bps = 1.0
            edge = score_edge_for_desk(
                votes=_pre.votes,
                spread_bps=max(0.0, float(analysis.spread_bps or 0.0)),
                impact_bps=rt_impact,
                fee_bps=rt_fee_bps,
                latency_bps=paper_latency_buffer_bps,
                take_profit_pct=float(settings.take_profit_pct),
                atr_pct=atr_now,
                regime=str(getattr(analysis, "regime", "unknown") or "unknown"),
                mode="paper",
                entry_min_score=float(settings.entry_min_score),
                paper_soft_gates=soft,
            )
        else:
            edge = score_edge_for_desk(
                votes=_pre.votes,
                spread_bps=max(0.0, float(analysis.spread_bps or 0.0)),
                impact_bps=rt_impact,
                fee_bps=rt_fee_bps,
                latency_bps=max(0.0, float(calibrated_latency_cost or 0.0)),
                take_profit_pct=float(settings.take_profit_pct),
                atr_pct=atr_now,
                regime=str(getattr(analysis, "regime", "unknown") or "unknown"),
                mode="live",
                entry_min_score=float(settings.entry_min_score),
                paper_soft_gates=False,
            )
    except Exception as exc:
        log.exception("score_edge failed; non-tradeable: %s", exc)
        from app.intelligence.edge import EdgeReport
        edge = EdgeReport(0.0, 0.0, 0.0, -999.0, False, [f"edge_error:{type(exc).__name__}"])
    execution_costs_calibrated = mode != "live" or calibrated_latency_cost is not None
    adv = adverse_filter.check(intend_long=True)
    whale_block = whale.side == "ask" and whale.strength >= 0.5
    adverse_reasons = list(adv.reasons)
    if whale_block:
        adverse_reasons.append(f"persistent_ask_wall:{whale.note}")
    decision = build_decision(
        analysis=analysis, sustained=sus, in_position=bool(ex and ex.base_quantity > 0),
        kill_switch=bool(risk.kill_switch), kill_reason=risk.kill_switch_reason,
        kelly_fraction=kd_preview.fraction, suggested_notional=kd_preview.notional_usdt,
        entry_min_score=effective_min_score,
        edge_tradeable=edge.tradeable and execution_costs_calibrated,
        edge_notes=edge.notes + ([] if execution_costs_calibrated else ["execution_cost_uncalibrated"]),
        adverse_toxic=adv.toxic or whale_block, adverse_reasons=adverse_reasons,
        autonomous_mode=auto_mode,
    )
    state.record_decision(decision)

    if ticks % 120 == 0:
        log.info(
            "pulse score=%.2f action=%s regime=%s edge_ok=%s flow=%s blockers=%s",
            analysis.score, decision.action, getattr(analysis, "regime", "?"),
            edge.tradeable, flow.note,
            ",".join(decision.blockers[:3]) if decision.blockers else "-",
        )

    auto = auto_mode
    flow_ok = bool(flow.bullish) if not auto else bool(flow.bullish or (flow.ready and flow.pressure > 0.05))
    if auto and not flow.ready and analysis.score >= max(settings.entry_min_score, 0.55):
        flow_ok = False

    churn_block = None
    now_ts = time.time()
    max_tph = int(getattr(settings, "max_trades_per_hour", 8) or 8)
    hourly = list(getattr(state, "hourly_trade_ts", []) or [])
    hourly = [x for x in hourly if now_ts - float(x) <= 3600.0]
    state.hourly_trade_ts = hourly
    if len(hourly) >= max_tph:
        churn_block = f"max_trades_per_hour:{len(hourly)}>={max_tph}"
    cool = float(getattr(settings, "entry_cooldown_seconds", 45.0) or 0.0)
    last_e = getattr(state, "last_entry_at", None)
    if churn_block is None and cool > 0 and last_e and (now_ts - float(last_e)) < cool:
        churn_block = f"entry_cooldown:{now_ts - float(last_e):.0f}s<{cool:.0f}s"
    max_fee = float(getattr(settings, "max_daily_fee_usdt", 3.0) or 3.0)
    sess_fee = float(getattr(state, "session_fees_usdt", 0.0) or 0.0)
    if churn_block is None and sess_fee >= max_fee:
        churn_block = f"max_daily_fee:{sess_fee:.2f}>={max_fee:.2f}"
    if churn_block and ticks % 90 == 0:
        log.info("anti_churn block: %s", churn_block)

    if not cb_allow and ticks % 90 == 0:
        try:
            snap = circuit_breaker.snapshot()
            log.info("circuit_breaker sleep: %s", snap.note)
        except Exception:
            pass

    can_enter = (
        decision.action == "enter_long"
        and ex is not None
        and ex.base_quantity <= 0
        and not risk.kill_switch
        and (signal is not None or auto)
        and (sus.ready or auto)
        and flow_ok
        and churn_block is None
        and cb_allow
    )
    try:
        bl = list(getattr(decision, "blockers", None) or [])
        if churn_block:
            bl = [str(churn_block)] + bl
        if not cb_allow:
            bl = ["circuit_breaker_sleep"] + bl
        state.blockers_live = bl[:12]
    except Exception:
        pass

    if can_enter:
        free_cash = ex.cash_usdt
        if mode == "live":
            try:
                ex.sync_balances()
                free_cash = ex.cash_usdt
            except Exception:
                log.exception("Balance sync failed")
                risk.activate_kill_switch("Exchange balance sync failed")
                state.last_error = "exchange_balance_sync_failed"
                persist()
                return confirmations, ticks
        atr_now = float(atr_tracker.atr_pct or 0.0)
        if bool(getattr(settings, "use_atr_targets", True)):
            dyn = compute_dynamic_targets(
                atr_pct=atr_now, spread_bps=float(analysis.spread_bps or 0.0),
                regime=str(analysis.regime or "unknown"),
            )
            rt = regime_targets(
                regime=str(analysis.regime or "unknown"),
                base_tp=float(dyn.take_profit_pct), base_sl=float(dyn.stop_loss_pct),
                base_trail=float(dyn.trailing_stop_pct), vol_bps=atr_now * 10_000.0,
            )
            active_tp, active_sl, active_trail = dyn.take_profit_pct, dyn.stop_loss_pct, dyn.trailing_stop_pct
            size_scale = float(rt.size_scale) * float(getattr(learner, "size_bias", 1.0) or 1.0)
        else:
            active_tp = float(settings.take_profit_pct)
            active_sl = float(settings.stop_loss_pct)
            active_trail = float(settings.trailing_stop_pct)
            size_scale = float(getattr(learner, "size_bias", 1.0) or 1.0)

        equity = float(free_cash)
        if bool(getattr(settings, "vol_target_enabled", True)) and active_sl > 0:
            risk_budget = equity * (float(getattr(settings, "risk_per_trade_pct", 0.40)) / 100.0)
            vol_notional = risk_budget / (active_sl / 100.0)
        else:
            vol_notional = float(settings.order_size_usdt)

        kd = kelly.size(free_usdt=free_cash, fee_rate=settings.effective_fee_rate(), size_scale=size_scale)
        base_n = kd.notional_usdt if kd.notional_usdt > 0 else size_from_free_cash(
            free_usdt=free_cash,
            allocation_fraction=float(getattr(learner, "compound_fraction", settings.compound_fraction) or settings.compound_fraction),
            max_order_usdt=settings.max_order_size_usdt,
            min_order_usdt=float(getattr(settings, "min_order_usdt", 5) or 5),
        ).notional_usdt
        compound = float(getattr(learner, "compound_fraction", None) or settings.compound_fraction)
        desired = min(max(base_n, 0.0), max(vol_notional, 0.0)) if base_n > 0 else max(vol_notional, 0.0)
        desired = desired * max(0.35, min(1.0, compound))
        desired = vol_adjusted_notional(
            base_notional=desired, size_scale=size_scale,
            min_order_usdt=float(getattr(settings, "min_order_usdt", 5) or 5),
            max_order_usdt=float(settings.max_order_size_usdt),
        )
        depth_vis = max(ask * max(ask_qty, 1e-9), 1.0) * 10.0
        try:
            liq = assess_liquidity(symbol=settings.symbol, bids=depth_bids, asks=depth_asks, spread_bps=analysis.spread_bps)
            depth_vis = max(liq.depth_usdt, depth_vis)
        except Exception:
            pass
        desired = impact_capped_notional(
            desired_usdt=desired, visible_depth_usdt=depth_vis, max_book_fraction=0.08,
            min_order_usdt=float(getattr(settings, "min_order_usdt", 5) or 5),
            max_order_usdt=float(settings.max_order_size_usdt),
        )
        sizing_n = portfolio_risk.size_for_budget(
            equity_usdt=equity, stop_loss_pct=active_sl, desired_usdt=desired, symbol=settings.symbol,
        )
        if sizing_n > 0:
            risk_dec = risk.evaluate_entry(
                notional_usdt=sizing_n, available_cash=free_cash, bid=bid, ask=ask,
                data_age_seconds=state.data_age_seconds(),
            )
            if risk_dec.allowed:
                try:
                    if mode == "paper":
                        prefer_maker = bool(getattr(settings, "prefer_maker", False))
                        entry_px = float(bid if prefer_maker else ask)
                        book_side = depth_bids if prefer_maker else depth_asks
                        qty = sizing_n / max(entry_px, 1e-12)
                        fill = await _paper_fill("buy", entry_px, qty, book_levels=book_side, stress=False)
                        actual = fill.filled_quantity * fill.fill_price
                        if actual > 0:
                            tag = "maker" if prefer_maker else "taker"
                            trade = ex.buy(
                                notional_usdt=actual, price=fill.fill_price,
                                reason=f"edge_enter;{tag}; sim_fill={fill.filled_quantity / fill.requested_quantity:.4f}; slip_bps={fill.slippage_bps:.1f}",
                            )
                            if trade:
                                store.append_trade(trade, event_key=_event_key(key, trade))
                                state.record_fill(trade)
                                state.peak_price = entry_px
                                state.position_tp_pct = active_tp
                                state.position_sl_pct = active_sl
                                state.position_trail_pct = active_trail
                                state.position_opened_at = time.time()
                                state.last_entry_at = time.time()
                                try:
                                    state.hourly_trade_ts = list(getattr(state, "hourly_trade_ts", []) or []) + [time.time()]
                                except Exception:
                                    pass
                                try:
                                    portfolio_risk.register(settings.symbol, sizing_n, active_sl)
                                except Exception:
                                    pass
                    else:
                        prefer_maker = bool(getattr(settings, "prefer_maker", False))
                        trade = None
                        if prefer_maker and hasattr(ex, "buy_limit"):
                            limit_px = min(float(bid), float(ask) * 0.9999)
                            try:
                                trade = ex.buy_limit(
                                    notional_usdt=sizing_n, limit_price=limit_px,
                                    reason="edge_enter; live_limit_maker", decision_mid=analysis.mid,
                                    wait_seconds=float(getattr(settings, "maker_wait_seconds", 8.0) or 8.0),
                                    post_only=True,
                                )
                            except Exception:
                                log.exception("buy_limit failed; no market fallback this tick")
                                trade = None
                        if trade is None and not prefer_maker:
                            trade = ex.buy(
                                notional_usdt=sizing_n, price=ask,
                                reason="edge_enter; live_market_buy", decision_mid=analysis.mid,
                            )
                        if trade:
                            if not trade.get("accounting_complete", True):
                                risk.activate_kill_switch("Exchange commission accounting incomplete")
                                state.last_error = "commission_accounting_incomplete"
                            if hasattr(ex, "install_protection_or_flatten"):
                                protected = ex.install_protection_or_flatten(
                                    current_price=ask, take_profit_pct=active_tp,
                                    stop_loss_pct=active_sl, mark_price=ask,
                                )
                                if not protected:
                                    risk.activate_kill_switch("Exchange-hosted TP/SL OCO unavailable — emergency flatten")
                                    state.last_error = "oco_install_failed"
                            store.append_trade(trade, event_key=_event_key(key, trade))
                            state.record_fill(trade)
                            state.peak_price = ask
                            state.position_tp_pct = active_tp
                            state.position_sl_pct = active_sl
                            state.position_trail_pct = active_trail
                            state.position_opened_at = time.time()
                            state.last_entry_at = time.time()
                            try:
                                state.hourly_trade_ts = list(getattr(state, "hourly_trade_ts", []) or []) + [time.time()]
                            except Exception:
                                pass
                            try:
                                portfolio_risk.register(settings.symbol, sizing_n, active_sl)
                            except Exception:
                                pass
                except Exception:
                    log.exception("Entry order failed")
                    state.last_error = "entry_failed"
                    if getattr(ex, "order_state_uncertain", False):
                        risk.activate_kill_switch("Exchange order outcome uncertain")
                    confirmations = 0
    persist()
    return confirmations, ticks
