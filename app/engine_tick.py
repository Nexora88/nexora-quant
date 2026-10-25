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
    simulator,
    state,
    sustained,
    wall_tracker,
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
    try:
        shadows.on_tick(
            score=analysis.score, bid=bid, ask=ask, size_usdt=settings.order_size_usdt,
            fee=settings.fee_rate, stop_pct=settings.stop_loss_pct, tp_pct=settings.take_profit_pct,
        )
        state.shadow_leaderboard = shadows.leaderboard(bid)
    except Exception:
        pass
    state.record_analysis(analysis)
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
                    fill = await _paper_fill("sell", bid, ex.base_quantity)
                    trade = ex.sell_quantity(
                        quantity=fill.filled_quantity, price=fill.fill_price,
                        reason=f"{reason}; sim_fill={fill.filled_quantity / fill.requested_quantity:.4f}",
                    )
                else:
                    trade = ex.sell_quantity(
                        quantity=ex.base_quantity, price=bid, reason=f"{reason}; live_market_sell",
                    )
                if trade:
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
    edge = score_edge(votes=_pre.votes, spread_bps=analysis.spread_bps, impact_bps=impact_est)
    adv = adverse_filter.check(intend_long=True)
    decision = build_decision(
        analysis=analysis, sustained=sus, in_position=bool(ex and ex.base_quantity > 0),
        kill_switch=bool(risk.kill_switch), kill_reason=risk.kill_switch_reason,
        kelly_fraction=kd_preview.fraction, suggested_notional=kd_preview.notional_usdt,
        entry_min_score=settings.entry_min_score,
        edge_tradeable=edge.tradeable, edge_notes=edge.notes,
        adverse_toxic=adv.toxic, adverse_reasons=adv.reasons,
    )
    state.record_decision(decision)

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
                        fill = await _paper_fill("buy", ask, qty)
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
                        )
                        store.append_trade(trade, event_key=_event_key(key, trade))
                        state.record_fill(trade)
                except Exception:
                    log.exception("Entry order failed")
                    state.last_error = "entry_failed"
                confirmations = 0
    persist()
    return confirmations, ticks
