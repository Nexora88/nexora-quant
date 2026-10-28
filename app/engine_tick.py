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
    kelly,
    log,
    ou_tracker,
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
            "symbol": settings.symbol,
            "best_bid": [bid, bid_qty],
            "best_ask": [ask, ask_qty],
            "update_id": getattr(depth, "last_update_id", None),
            "bids": sorted(getattr(depth, "bids", {}).items(), reverse=True)[:20],
            "asks": sorted(getattr(depth, "asks", {}).items())[:20],
        },
    )
    if bid <= 0 or ask < bid:
        return confirmations, ticks
    risk.rollover_day(datetime.now(timezone.utc).date().isoformat())
    state.update_book(
        BookTicker(settings.symbol, bid, bid_qty, ask, ask_qty, datetime.now(timezone.utc))
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
            take_profit_pct=settings.take_profit_pct, stop_loss_pct=settings.stop_loss_pct,
            trailing_stop_pct=settings.trailing_stop_pct, peak_price=state.peak_price,
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
            except Exception:
                log.exception("Exit order failed (%s)", reason)
                state.last_error = f"exit_failed:{reason}"
                if getattr(ex, "order_state_uncertain", False):
                    risk.activate_kill_switch("Exchange order outcome uncertain")
            persist()
            return confirmations, ticks

    signal = entry_signal_from_analysis(analysis, min_score=settings.entry_min_score)
    state.record_signal(signal)
    sus = sustained.update(analysis.score if signal else 0.0)
    confirmations = sus.consecutive
    free = getattr(ex, "cash_usdt", settings.starting_cash_usdt) if ex else settings.starting_cash_usdt
    kd_preview = kelly.size(free_usdt=free, fee_rate=settings.fee_rate)
    adverse_filter.update(mid=analysis.mid, spread_bps=analysis.spread_bps, micro_price=analysis.micro_price)
    _pre = build_decision(
        analysis=analysis, sustained=sus, in_position=bool(ex and ex.base_quantity > 0),
        kill_switch=bool(risk.kill_switch), kill_reason=risk.kill_switch_reason,
        kelly_fraction=kd_preview.fraction, suggested_notional=kd_preview.notional_usdt,
        entry_min_score=settings.entry_min_score,
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
    # Paper: softer edge so the desk can learn; live keeps cost-aware gate.
    if mode == "paper":
        edge = score_edge(
            votes=_pre.votes,
            spread_bps=analysis.spread_bps,
            impact_bps=2.0 * impact_est,
            fee_bps=2.0 * settings.fee_rate * 10_000,
            latency_bps=0.0,
            min_quality=0.18,
            min_net_edge_bps=-12.0,
        )
    else:
        edge = score_edge(
            votes=_pre.votes,
            spread_bps=analysis.spread_bps,
            impact_bps=2.0 * impact_est,
            fee_bps=2.0 * settings.fee_rate * 10_000,
            latency_bps=calibrated_latency_cost or 0.0,
        )
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
    )
    state.record_decision(decision)

    if ticks % 120 == 0:
        log.info(
            "pulse score=%.2f action=%s regime=%s edge_ok=%s blockers=%s",
            analysis.score,
            decision.action,
            getattr(analysis, "regime", "?"),
            edge.tradeable,
            ",".join(decision.blockers[:3]) if decision.blockers else "-",
        )

    if (
        decision.action == "enter_long" and signal and sus.ready
        and ex and ex.base_quantity <= 0 and not risk.kill_switch
    ):
        free_cash = ex.cash_usdt
        if mode == "live":
            try:
                ex.sync_balances()
                free_cash = ex.cash_usdt
            except Exception:
                log.exception("Balance sync failed")
                risk.activate_kill_switch("Exchange balance sync failed")
                state.last_error = "exchange_balance_sync_failed"
        kd = kelly.size(free_usdt=free_cash, fee_rate=settings.fee_rate)
        sizing_n = kd.notional_usdt if kd.notional_usdt > 0 else size_from_free_cash(
            free_usdt=free_cash, allocation_fraction=0.8, fee_rate=settings.fee_rate,
            max_order_usdt=min(settings.order_size_usdt, settings.max_order_size_usdt),
            min_order_usdt=5,
        ).notional_usdt
        if sizing_n > 0:
            risk_dec = risk.evaluate_entry(
                notional_usdt=sizing_n, available_cash=free_cash, bid=bid, ask=ask,
                data_age_seconds=state.data_age_seconds(),
            )
            if risk_dec.allowed:
                try:
                    if mode == "paper":
                        qty = sizing_n / ask
                        fill = await _paper_fill("buy", ask, qty, book_levels=depth_asks)
                        actual = fill.filled_quantity * fill.fill_price
                        if actual > 0:
                            trade = ex.buy(
                                notional_usdt=actual, price=fill.fill_price,
                                reason=f"{signal.reason}; score={analysis.score:.2f}",
                            )
                            store.append_trade(trade, event_key=_event_key(key, trade))
                            state.record_fill(trade)
                    else:
                        trade = ex.buy(
                            notional_usdt=sizing_n, price=ask,
                            reason=f"{signal.reason}; score={analysis.score:.2f}; live_buy",
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
                                take_profit_pct=settings.take_profit_pct,
                                stop_loss_pct=settings.stop_loss_pct,
                                mark_price=float(bid or ask),
                            )
                        elif not ex.ensure_protective_oco(
                            current_price=ask,
                            take_profit_pct=settings.take_profit_pct,
                            stop_loss_pct=settings.stop_loss_pct,
                        ):
                            protected = False
                        if not protected:
                            state.emergency = True
                            state.last_error = "protective_oco_install_failed"
                            risk.activate_kill_switch(
                                "Exchange-hosted TP/SL OCO unavailable — emergency flatten"
                            )
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
