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
        log.debug("feature append failed", exp_info=True)

    ticks += 1
    if ticks % 15 == 0:
        state.sample_equity()

    # PLACEHOLDER_BODY — will be completed
    return confirmations, ticks
