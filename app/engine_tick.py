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
from app.intelligence.edge import score_edge
from app.portfolio import size_from_free_cash
from app.atr_stops import compute_dynamic_targets
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
            ts_ns=time.time_ns(), symbol=settings.symbol, mid=analysis.mid,
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
        reason = exit_reason(
            bid=bid, average_entry=ex.average_entry_price,
            take_profit_pct=float(state.position_tp_pct or settings.take_profit_pct),
            stop_loss_pct=float(state.position_sl_pct or settings.stop_loss_pct),
            trailing_stop_pct=float(state.position_trail_pct or settings.trailing_stop_pct),
            peak_price=state.peak_price,
            target_price=settings.target_price,
        )
        if reason:
            try:
                if mode == "paper":
                    stress = reason in ("stop_loss", "trailing_stop")
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
            except Exception:
                log.exception("Exit order failed (%s)", reason)
                state.last_error = f"exit_failed:{reason}"
                if getattr(ex, "order_state_uncertain", False):
                    risk.activate_kill_switch("Exchange order outcome uncertain")
            persist()
            return confirmations, ticks

    signal = entry_signal_from_analysis(analysis, min_score=settings.entry_min_score)
    state.record_signal(signal)
    sus = sustained.update(analysis.score if analysis.score >= settings.entry_min_score else 0.0)
    confirmations = sus.consecutive
    free = getattr(ex, "cash_usdt", settings.starting_cash_usdt) if ex else settings.starting_cash_usdt
    kd_preview = kelly.size(free_usdt=free, fee_rate=settings.fee_rate)
    adverse_filter.update(mid=analysis.mid, spread_bps=analysis.spread_bps, micro_price=analysis.micro_price)
    auto_mode = bool(getattr(settings, "autonomous_mode", True))
    _pre = build_decision(
        analysis=analysis, sustained=sus, in_position=bool(ex and ex.base_quantity > 0),
        kill_switch=bool(risk.kill_switch), kill_reason=risk.kill_switch_reason,
        kelly_fraction=kd_preview.fraction, suggested_notional=kd_preview.notional_usdt,
        entry_min_score=settings.entry_min_score,
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
        if mode == "paper":
            edge = score_edge(
                votes=_pre.votes,
                spread_bps=max(0.0, float(analysis.spread_bps or 0.0)),
                impact_bps=max(0.0, float(impact_est or 0.0)),
                fee_bps=max(0.0, float(settings.fee_rate) * 10_000),
                latency_bps=0.0,
                expected_alpha_bps=22.0,
                min_quality=0.22,
                min_net_edge_bps=-6.0,
            )
        else:
            edge = score_edge(
                votes=_pre.votes,
                spread_bps=max(0.0, float(analysis.spread_bps or 0.0)),
                impact_bps=max(0.0, 2.0 * float(impact_est or 0.0)),
                fee_bps=max(0.0, 2.0 * float(settings.fee_rate) * 10_000),
                latency_bps=max(0.0, float(calibrated_latency_cost or 0.0)),
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
        entry_min_score=settings.entry_min_score,
        edge_tradeable=edge.tradeable and execution_costs_calibrated,
        edge_notes=edge.notes + ([] if execution_costs_calibrated else ["execution_cost_uncalibrated"]),
        adverse_toxic=adv.toxic or whale_block, adverse_reasons=adverse_reasons,
        autonomous_mode=auto_mode,
    )
    state.record_decision(decision)

    if ticks % 120 == 0:
        log.info(
            "pulse score=%.2f action=%s regime=%s edge_ok=%s flow=%s blockers=%s",
            analysis.score,
            decision.action,
            getattr(analysis, "regime", "?"),
            edge.tradeable,
            flow.note,
            ",".join(decision.blockers[:3]) if decision.blockers else "-",
        )

    auto = auto_mode
    flow_ok = bool(flow.bullish) if not auto else bool(flow.bullish or (flow.ready and flow.pressure > 0.05))
    if auto and not flow.ready and analysis.score >= max(settings.entry_min_score, 0.55):
        flow_ok = False
    can_enter = (
        decision.action == "enter_long"
        and ex is not None
        and ex.base_quantity <= 0
        and not risk.kill_switch
        and (signal is not None or auto)
        and (sus.ready or auto)
        and flow_ok
    )
    if not can_enter and decision.action == "enter_long" and ticks % 30 == 0:
        log.info(
            "enter_long held signal=%s sus_ready=%s auto=%s flow=%s pos=%s kill=%s",
            bool(signal),
            sus.ready,
            auto,
            flow.note,
            bool(ex and ex.base_quantity > 0),
            bool(risk.kill_switch),
        )
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
        atr_now = float(atr_tracker.atr_pct or 0.0)
        if bool(getattr(settings, "use_atr_targets", True)):
            dyn = compute_dynamic_targets(
                atr_pct=atr_now,
                spread_bps=float(analysis.spread_bps or 0.0),
                regime=str(analysis.regime or "unknown"),
            )
            rt = regime_targets(
                regime=str(analysis.regime or "unknown"),
                base_tp=float(dyn.take_profit_pct),
                base_sl=float(dyn.stop_loss_pct),
                base_trail=float(dyn.trailing_stop_pct),
                vol_bps=atr_now * 10_000.0,
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

        kd = kelly.size(free_usdt=free_cash, fee_rate=settings.fee_rate, size_scale=size_scale)
        base_n = kd.notional_usdt if kd.notional_usdt > 0 else size_from_free_cash(
            free_usdt=free_cash,
            allocation_fraction=float(getattr(learner, "compound_fraction", settings.compound_fraction) or 0.85),
            fee_rate=settings.fee_rate,
            max_order_usdt=min(settings.order_size_usdt, settings.max_order_size_usdt),
            min_order_usdt=float(getattr(settings, "min_order_usdt", 5) or 5),
        ).notional_usdt
        compound = float(getattr(learner, "compound_fraction", None) or settings.compound_fraction)
        desired = min(max(base_n, 0.0), max(vol_notional, 0.0)) if base_n > 0 else max(vol_notional, 0.0)
        desired = desired * max(0.35, min(1.0, compound))
        desired = vol_adjusted_notional(
            base_notional=desired,
            size_scale=size_scale,
            min_order_usdt=float(getattr(settings, "min_order_usdt", 5) or 5),
            max_order_usdt=float(settings.max_order_size_usdt),
        )
        depth_vis = max(ask * max(ask_qty, 1e-9), 1.0) * 10.0
        try:
            liq = assess_liquidity(symbol=settings.symbol, bids=depth_bids, asks=depth_asks, spread_bps=analysis.spread_bps)
            depth_vis = max(liq.depth_usdt, depth_vis)
            if not liq.ok and ticks % 40 == 0:
                log.info("liquidity soft-warn: %s", liq.note)
        except Exception:
            pass
        desired = impact_capped_notional(
            desired_usdt=desired,
            visible_depth_usdt=depth_vis,
            max_book_fraction=0.08,
            min_order_usdt=float(getattr(settings, "min_order_usdt", 5) or 5),
            max_order_usdt=float(settings.max_order_size_usdt),
        )
        sizing_n = portfolio_risk.size_for_budget(
            equity_usdt=equity,
            stop_loss_pct=active_sl,
            desired_usdt=desired,
            symbol=settings.symbol,
        )
        state.last_sizing_note = (
            f"n={sizing_n:.2f} vol={vol_notional:.2f} kelly={base_n:.2f} "
            f"sl={active_sl:.2f} tp={active_tp:.2f} scale={size_scale:.2f}"
        )
        if sizing_n > 0:
            risk_dec = risk.evaluate_entry(
                notional_usdt=sizing_n, available_cash=free_cash, bid=bid, ask=ask,
                data_age_seconds=state.data_age_seconds(),
            )
            if not risk_dec.allowed:
                if ticks % 50 == 0:
                    log.info("risk denied: %s", risk_dec.reason)
            elif risk_dec.allowed:
                try:
                    if mode == "paper":
                        qty = sizing_n / ask
                        fill = await _paper_fill("buy", ask, qty, book_levels=depth_asks)
                        actual = fill.filled_quantity * fill.fill_price
                        if actual > 0:
                            trade = ex.buy(
                                notional_usdt=actual, price=fill.fill_price,
                                reason=f"{(signal.reason if signal else 'auto')}; score={analysis.score:.2f}; {flow.note}",
                            )
                            store.append_trade(trade, event_key=_event_key(key, trade))
                            state.record_fill(trade)
                            state.position_tp_pct = active_tp
                            state.position_sl_pct = active_sl
                            state.position_trail_pct = active_trail
                            state.dynamic_targets_note = f"tp={active_tp:.2f}|sl={active_sl:.2f}"
                            try:
                                portfolio_risk.register(settings.symbol, actual, active_sl)
                            except Exception:
                                pass
                            log.info(
                                "paper BUY filled notional=%.2f score=%.2f tp=%.2f sl=%.2f %s %s",
                                actual, analysis.score, active_tp, active_sl,
                                state.last_sizing_note or "", flow.note,
                            )
                    else:
                        trade = ex.buy(
                            notional_usdt=sizing_n, price=ask,
                            reason=f"{(signal.reason if signal else 'auto')}; score={analysis.score:.2f}; live_buy",
                            decision_mid=analysis.mid,
                        )
                        if trade.get("execution_latency_measured", False) and hasattr(es, "execution_costs"):
                            es.execution_costs.record_fill(
                                side=trade["side"], decision_mid=float(trade["decision_mid"]),
                                fill_price=float(trade["price"]),
                                latency_ms=float(trade["execution_latency_ms"]),
                                filled_at_ms=int(time.time() * 1000),
                            )
                        if not trade.get("accounting_complete", False):
                            risk.activate_kill_switch("Exchange commission accounting incomplete")
                            state.last_error = "commission_accounting_incomplete"
                        protected = True
                        if hasattr(ex, "install_protection_or_flatten"):
                            protected = ex.install_protection_or_flatten(
                                current_price=ask,
                                take_profit_pct=active_tp,
                                stop_loss_pct=active_sl,
                                mark_price=float(bid or ask),
                            )
                        elif not ex.ensure_protective_oco(
                            current_price=ask,
                            take_profit_pct=active_tp,
                            stop_loss_pct=active_sl,
                        ):
                            protected = False
                        if not protected:
                            state.emergency = True
                            state.last_error = "protective_oco_install_failed"
                            risk.activate_kill_switch(
                                "Exchange-hosted TP/SL OCO unavailable — emergency flatten"
                            )
                        state.position_tp_pct = active_tp
                        state.position_sl_pct = active_sl
                        state.position_trail_pct = active_trail
                        try:
                            portfolio_risk.register(settings.symbol, sizing_n, active_sl)
                        except Exception:
                            pass
                        store.append_trade(trade, event_key=_event_key(key, trade))
                        state.record_fill(trade)
                except Exception:
                    log.exception("Entry order failed")
                    state.last_error = "entry_failed"
                    if getattr(ex, "order_state_uncertain", False):
                        risk.activate_kill_switch("Exchange order outcome uncertain")
                confirmations = 0
    persist()
    return confirmations, ticks
