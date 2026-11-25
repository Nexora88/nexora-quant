"""Per-depth-tick trading core.

Body: app/_et_b64/body.z0 + body.z1 (zlib+base64).
Loader wraps handle_tick with TARGET_EQUITY soft-halt and paper milestones.
"""
from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import asdict

from app.order_flow import FlowPressure
from app.engine_setup import state as _runtime_state, spoof_filter as _spoof_filter
from app.profit_lock import net_profit_lock_reason
from app.expectancy import pessimistic_slippage_pct
import app.engine_tick_body as _body

# Keep the trading loop in ordinary, reviewable Python source. The legacy
# compressed body files remain untouched for audit/recovery until removal.
_ns: dict = vars(_body)
_inner_handle_tick = _ns["handle_tick"]

# Down-weight transient L2 liquidity before the composite score is consumed.
_base_analyze_market = _ns["analyze_market"]


def _analyze_with_persistent_depth(**kwargs):
    from app.config import settings
    symbol = str(getattr(_runtime_state, "trade_symbol", None) or settings.symbol).lower()
    indicator_trackers = getattr(_runtime_state, "market_indicator_trackers", None) or {}
    indicator_tracker = indicator_trackers.get(symbol)
    indicator = indicator_tracker.snapshot() if indicator_tracker is not None else None
    if indicator is not None and indicator.ready and indicator_tracker is not None:
        # Use the last two fully closed candles for each horizon. This avoids
        # waiting five minutes after every router selection to rebuild tick history.
        kwargs.setdefault(
            "momentum_1m_override_bps",
            indicator_tracker.return_bps(interval="1m", bars=1),
        )
        kwargs.setdefault(
            "momentum_5m_override_bps",
            indicator_tracker.return_bps(interval="5m", bars=1),
        )
    analysis = _base_analyze_market(**kwargs)
    bids = kwargs.get("bids") or []
    asks = kwargs.get("asks") or []
    symbol = str(getattr(_runtime_state, "trade_symbol", None) or "unknown").lower()
    spoof_filter = _symbol_spoof_filters.get(symbol, _spoof_filter)
    report = spoof_filter.update(bids, asks)
    _runtime_state.last_depth_quality = {
        "spoof_score": report.spoof_score,
        "stable_bid_usdt": report.stable_bid_usdt,
        "stable_ask_usdt": report.stable_ask_usdt,
        "transient_bid_usdt": report.transient_bid_usdt,
        "transient_ask_usdt": report.transient_ask_usdt,
        "note": report.note,
    }
    _runtime_state.last_market_indicators = asdict(indicator) if indicator is not None else {
        "ready": False, "note": "indicator_history_unavailable", "symbol": symbol,
    }
    if indicator is not None and indicator.ready:
        if indicator.trend_bias == "bullish" and indicator.momentum_bias == "bullish":
            analysis.score = min(1.0, analysis.score + 0.08)
            analysis.reasons.append("indicator_trend_and_momentum_bullish")
        elif indicator.trend_bias == "bearish" or indicator.momentum_bias == "bearish":
            analysis.score = max(-1.0, analysis.score - 0.12)
            analysis.reasons.append("indicator_bearish_context")
    if report.spoof_score >= 0.70:
        analysis.score *= max(0.20, 1.0 - report.spoof_score)
        analysis.reasons.append(f"transient_depth_risk={report.spoof_score:.2f}")
    return analysis


_ns["analyze_market"] = _analyze_with_persistent_depth


# Entry flow must be confirmed by persistent L2 pressure and actual aggressor trades.
# A stale/missing trade stream or high transient-liquidity risk fails closed.
_base_order_flow = _ns["order_flow"]


class _TradeConfirmedOrderFlow:
    def __init__(self, base):
        self.base = base

    def update(self, *, imbalance: float, micro_premium_bps: float = 0.0):
        book_flow = self.base.update(
            imbalance=imbalance, micro_premium_bps=micro_premium_bps
        )
        _runtime_state.last_book_flow = {
            "pressure": book_flow.pressure,
            "ready": book_flow.ready,
            "note": book_flow.note,
            "samples": book_flow.samples,
        }
        from app.config import settings
        symbol = str(getattr(_runtime_state, "trade_symbol", None) or settings.symbol).lower()
        depth_quality = getattr(_runtime_state, "last_depth_quality", None) or {}
        if float(depth_quality.get("spoof_score", 0.0) or 0.0) >= 0.70:
            return FlowPressure(
                book_flow.pressure, book_flow.samples, book_flow.hold_seconds,
                False, f"spoof_risk:{float(depth_quality.get('spoof_score', 0.0)):.2f}",
            )
        indicator_trackers = getattr(_runtime_state, "market_indicator_trackers", None) or {}
        indicator_tracker = indicator_trackers.get(symbol)
        indicator = indicator_tracker.snapshot() if indicator_tracker is not None else None
        if indicator is None or not indicator.ready:
            return FlowPressure(
                book_flow.pressure, book_flow.samples, book_flow.hold_seconds,
                False, "indicator_history_warming_or_stale",
            )
        if indicator.trend_bias == "bearish" or indicator.momentum_bias == "bearish":
            return FlowPressure(
                book_flow.pressure, book_flow.samples, book_flow.hold_seconds,
                False, "indicator_bearish_context",
            )
        atr_pct = indicator.atr14_pct
        volume_ratio = indicator.volume_ratio
        if atr_pct is not None and atr_pct >= 0.80:
            return FlowPressure(
                book_flow.pressure, book_flow.samples, book_flow.hold_seconds,
                False, f"atr_volatility_stress:{atr_pct:.3f}%",
            )
        if volume_ratio is not None and volume_ratio < 0.20:
            return FlowPressure(
                book_flow.pressure, book_flow.samples, book_flow.hold_seconds,
                False, f"volume_too_thin:{volume_ratio:.2f}x",
            )
        if volume_ratio is not None and volume_ratio >= 4.0 and atr_pct is not None and atr_pct >= 0.60:
            return FlowPressure(
                book_flow.pressure, book_flow.samples, book_flow.hold_seconds,
                False, f"volume_volatility_spike:{volume_ratio:.2f}x/{atr_pct:.3f}%",
            )
        if symbol != "btcusdt":
            btc_tracker = indicator_trackers.get("btcusdt")
            btc_indicator = btc_tracker.snapshot() if btc_tracker is not None else None
            if btc_indicator is None or not btc_indicator.ready:
                return FlowPressure(
                    book_flow.pressure, book_flow.samples, book_flow.hold_seconds,
                    False, "btc_context_warming_or_stale",
                )
            btc_return = btc_tracker.return_bps(bars=5)
            asset_return = indicator_tracker.return_bps(bars=5)
            corr = indicator_tracker.correlation_with(btc_tracker, periods=30)
            eth_tracker = indicator_trackers.get("ethusdt")
            eth_return = eth_tracker.return_bps(bars=5) if eth_tracker is not None else None
            macro = {
                "btc_return_5m_bps": btc_return,
                "asset_return_5m_bps": asset_return,
                "relative_strength_5m_bps": (
                    asset_return - btc_return
                    if asset_return is not None and btc_return is not None else None
                ),
                "btc_correlation_30m": corr,
                "eth_return_5m_bps": eth_return,
                "ready": btc_return is not None and asset_return is not None,
            }
            _runtime_state.last_macro_context = macro
            if not macro["ready"]:
                return FlowPressure(
                    book_flow.pressure, book_flow.samples, book_flow.hold_seconds,
                    False, "macro_returns_warming",
                )
            if btc_return <= -25.0 and (corr is None or corr >= 0.45):
                return FlowPressure(
                    book_flow.pressure, book_flow.samples, book_flow.hold_seconds,
                    False, "btc_macro_downtrend",
                )
            if asset_return - btc_return < -20.0:
                return FlowPressure(
                    book_flow.pressure, book_flow.samples, book_flow.hold_seconds,
                    False, "relative_strength_vs_btc_weak",
                )
            if symbol != "ethusdt" and btc_return < 0 and eth_return is not None and eth_return <= -30.0:
                return FlowPressure(
                    book_flow.pressure, book_flow.samples, book_flow.hold_seconds,
                    False, "major_market_breadth_weak",
                )
        else:
            _runtime_state.last_macro_context = {
                "btc_return_5m_bps": indicator_tracker.return_bps(bars=5),
                "btc_correlation_30m": 1.0,
                "ready": True,
            }
        trackers = getattr(_runtime_state, "trade_flow_trackers", None) or {}
        tracker = trackers.get(symbol)
        trade_flow = tracker.snapshot() if tracker is not None else None
        if trade_flow is None:
            _runtime_state.last_trade_flow = {
                "ready": False, "note": "trade_flow:no_stream", "symbol": symbol
            }
            return FlowPressure(
                book_flow.pressure, book_flow.samples, book_flow.hold_seconds,
                False, "trade_flow:no_stream",
            )
        _runtime_state.last_trade_flow = {
            "ready": trade_flow.ready,
            "note": trade_flow.note,
            "symbol": symbol,
            "buy_qty": trade_flow.buy_qty,
            "sell_qty": trade_flow.sell_qty,
            "delta_qty": trade_flow.delta_qty,
            "cvd": trade_flow.cvd,
            "buy_sell_ratio": trade_flow.buy_sell_ratio,
            "delta_ratio": trade_flow.delta_ratio,
            "trades": trade_flow.trades,
            "age_seconds": trade_flow.age_seconds,
        }
        if not trade_flow.ready:
            return FlowPressure(
                book_flow.pressure, book_flow.samples, book_flow.hold_seconds,
                False, trade_flow.note,
            )
        fused = 0.55 * book_flow.pressure + 0.45 * trade_flow.delta_ratio
        ready = book_flow.ready and abs(fused) >= 0.10
        return FlowPressure(
            fused, book_flow.samples, book_flow.hold_seconds, ready,
            f"{book_flow.note}; {trade_flow.note}",
        )


_ns["order_flow"] = _TradeConfirmedOrderFlow(_base_order_flow)


_base_exit_reason = _ns["exit_reason"]


def _exit_with_net_profit_lock(**kwargs):
    base_reason = _base_exit_reason(**kwargs)
    if base_reason is not None:
        return base_reason
    from app.config import settings
    symbol = str(getattr(_runtime_state, "trade_symbol", None) or settings.symbol).lower()
    slippage_bps = max(
        float(getattr(settings, "simulated_slippage_bps", 0.0) or 0.0),
        pessimistic_slippage_pct(symbol, stress=False) * 100.0,
    )
    return net_profit_lock_reason(
        bid=float(kwargs.get("bid") or 0.0),
        average_entry=float(kwargs.get("average_entry") or 0.0),
        peak_price=float(kwargs.get("peak_price") or 0.0),
        fee_rate=float(settings.effective_fee_rate()),
        slippage_bps_per_side=slippage_bps,
        momentum_1m_bps=kwargs.get("momentum_1m_bps"),
        momentum_5m_bps=kwargs.get("momentum_5m_bps"),
        trade_flow=getattr(_runtime_state, "last_trade_flow", None),
        book_flow=getattr(_runtime_state, "last_book_flow", None),
    )


_ns["exit_reason"] = _exit_with_net_profit_lock


# Per-symbol rolling state: never let BTC prices/OBI contaminate another asset.
_symbol_contexts = {}
_symbol_order_flows = {}
_symbol_spoof_filters = {}
_active_symbol_key = None
_SYMBOL_RUNTIME_FIELDS = (
    "last_analysis", "last_signal", "last_decision", "decision_history",
    "score_history", "score_ema", "_score_ema_seeded", "last_flow",
    "last_book_flow", "last_trade_flow", "last_depth_quality",
    "last_market_indicators", "last_macro_context", "blockers_live",
    "last_entry_eligible", "motor_report",
)


def _activate_symbol_context(symbol: str) -> None:
    from app.strategy import PriceWindow
    from app.analytics.microstructure import OrnsteinUhlenbeckTracker
    from app.analytics.regime import RegimeClassifier
    from app.analytics.walls import WallTracker
    from app.order_flow import OrderFlowAccumulator
    from app.atr_stops import AtrTracker
    from app.analytics.sustained import SustainedSignalGate
    from app.intelligence.adverse import AdverseSelectionFilter
    from app.intelligence.whale import WhaleTracker
    from app.intelligence.spoof import OrderPersistenceFilter
    from app.config import settings

    global _active_symbol_key
    key = str(symbol or settings.symbol).lower()
    if _active_symbol_key and _active_symbol_key != key:
        saved = {}
        for field in _SYMBOL_RUNTIME_FIELDS:
            if hasattr(_runtime_state, field):
                saved[field] = deepcopy(getattr(_runtime_state, field))
        _runtime_state.symbol_runtime_state[_active_symbol_key] = saved
    saved = _runtime_state.symbol_runtime_state.get(key)
    if saved is not None:
        for field in _SYMBOL_RUNTIME_FIELDS:
            if field in saved:
                setattr(_runtime_state, field, deepcopy(saved[field]))
    else:
        from collections import deque
        defaults = {
            "last_analysis": None, "last_signal": None, "last_decision": None,
            "decision_history": deque(maxlen=50), "score_history": deque(maxlen=180),
            "score_ema": 0.0, "_score_ema_seeded": False, "last_flow": None,
            "last_book_flow": None, "last_trade_flow": None, "last_depth_quality": None,
            "last_market_indicators": None, "last_macro_context": None,
            "blockers_live": [], "last_entry_eligible": False, "motor_report": None,
        }
        for field, value in defaults.items():
            setattr(_runtime_state, field, deepcopy(value))
    _active_symbol_key = key
    ctx = _symbol_contexts.get(key)
    if ctx is None:
        ctx = {
            "price_window": PriceWindow(maxlen=1200, sample_interval_seconds=0.5),
            "ou_tracker": OrnsteinUhlenbeckTracker(maxlen=300, z_entry=2.0),
            "regime_clf": RegimeClassifier(),
            "wall_tracker": WallTracker(levels=15, multiple=3.0),
            "atr_tracker": AtrTracker(period=28),
            "sustained": SustainedSignalGate(
                min_confirmations=max(1, int(settings.signal_confirmations)),
                min_hold_seconds=1.5,
                min_score=float(settings.entry_min_score),
            ),
            "adverse_filter": AdverseSelectionFilter(),
            "whale_tracker": WhaleTracker(multiple=4.0, persist_ticks=5),
            "spoof_filter": OrderPersistenceFilter(min_persist_ms=1500.0),
            "order_flow": OrderFlowAccumulator(
                hold_seconds=1.8, min_samples=7, min_abs_pressure=0.14
            ),
        }
        _symbol_contexts[key] = ctx
        _symbol_spoof_filters[key] = ctx["spoof_filter"]
        _symbol_order_flows[key] = _TradeConfirmedOrderFlow(ctx["order_flow"])
    # The body module resolves these names from its module globals on each tick.
    for name, value in ctx.items():
        if name != "spoof_filter":
            _ns[name] = value
    _ns["order_flow"] = _symbol_order_flows[key]


def reset_depth_confirmation(symbol: str) -> None:
    """Do not count confirmations accumulated across missing depth events."""
    ctx = _symbol_contexts.get(symbol.lower())
    if ctx is not None:
        ctx["sustained"].reset()
        ctx["order_flow"].reset()


async def handle_tick(depth, store, history, features, mode, key, persist, confirmations, ticks):
    """Core tick + soft equity goal halt (new entries only; exits still run)."""
    from app.config import settings as _settings
    symbol = str(getattr(_runtime_state, "trade_symbol", None) or _settings.symbol).lower()
    _activate_symbol_context(symbol)
    try:
        from app.config import settings
        from app.goal import evaluate_goal, paper_milestones
        from app.engine_setup import state, log

        ex = getattr(state, "executor", None)
        bid = None
        try:
            if depth is not None and getattr(depth, "best_bid", None):
                bid = float(depth.best_bid[0])
        except Exception:
            bid = None
        mark_eq = None
        if ex is not None:
            try:
                snap = ex.snapshot(bid)
                mark_eq = float(snap.get("equity_usdt") or snap.get("cash_usdt") or 0.0)
            except Exception:
                mark_eq = float(getattr(ex, "cash_usdt", 0.0) or 0.0)

        g = evaluate_goal(
            bid=bid,
            equity_usdt=mark_eq,
            target_price=getattr(settings, "target_price", None),
            target_equity_usdt=getattr(settings, "target_equity_usdt", None),
        )
        ms = paper_milestones(
            equity_usdt=mark_eq,
            starting_cash_usdt=float(getattr(settings, "starting_cash_usdt", 100.0) or 100.0),
        )
        state.goal_status = {
            "note": g.note,
            "halt_entries": bool(g.halt_entries),
            "price_hit": bool(g.price_hit),
            "equity_hit": bool(g.equity_hit),
            "equity_usdt": mark_eq,
            "target_equity_usdt": getattr(settings, "target_equity_usdt", None),
            "target_price": getattr(settings, "target_price", None),
            **ms,
        }

        flat = ex is None or float(getattr(ex, "base_quantity", 0) or 0) <= 0
        if g.halt_entries and flat:
            # Saturate hourly anti-churn so body refuses new entries; exits unaffected.
            n = int(getattr(settings, "max_trades_per_hour", 8) or 8) + 2
            now = time.time()
            state.hourly_trade_ts = [now] * n
            bl = list(getattr(state, "blockers_live", None) or [])
            note = f"goal_halt:{g.note}"
            if note not in bl:
                state.blockers_live = [note] + bl[:11]
            if ticks % 60 == 0:
                log.info(
                    "goal soft-halt entries: %s equity=%.2f milestone=%s",
                    g.note,
                    mark_eq or 0.0,
                    ms.get("milestone"),
                )
    except Exception:
        pass

    result = await _inner_handle_tick(
        depth, store, history, features, mode, key, persist, confirmations, ticks
    )
    # Do not refresh diagnostics or router eligibility on an invalid/stale depth tick.
    if not isinstance(result, tuple) or len(result) != 2 or result[1] <= ticks:
        return result
    # Keep a compact, per-coin explanation for the dashboard instead of exposing
    # only whichever symbol happened to be processed most recently.
    try:
        diagnostics = getattr(_runtime_state, "symbol_diagnostics", None)
        if diagnostics is None:
            diagnostics = {}
            _runtime_state.symbol_diagnostics = diagnostics
        analysis = getattr(_runtime_state, "last_analysis", None) or {}
        decision = getattr(_runtime_state, "last_decision", None) or {}
        diagnostics[symbol] = {
            "symbol": symbol,
            "score": analysis.get("score") if isinstance(analysis, dict) else None,
            "regime": analysis.get("regime") if isinstance(analysis, dict) else None,
            "action": decision.get("action") if isinstance(decision, dict) else None,
            "entry_eligible": bool(getattr(_runtime_state, "last_entry_eligible", False)),
            "blockers": list(getattr(_runtime_state, "blockers_live", []) or [])[:12],
            "flow": dict(getattr(_runtime_state, "last_flow", None) or {}),
            "indicators": dict(getattr(_runtime_state, "last_market_indicators", None) or {}),
            "updated_at": time.time(),
        }
        router = getattr(__import__("app.engine_setup", fromlist=["symbol_router"]), "symbol_router", None)
        if router is not None and isinstance(analysis, dict):
            router.update_analysis(
                symbol,
                score=float(decision.get("score", analysis.get("score", 0.0)) or 0.0),
                regime=str(decision.get("regime", analysis.get("regime", "unknown")) or "unknown"),
                spoof_score=float((getattr(_runtime_state, "last_depth_quality", None) or {}).get("spoof_score", 0.0) or 0.0),
                btc_blocked=bool(getattr(_runtime_state, "btc_block", False)),
                reasons=list(getattr(decision, "get", lambda *_: [])("blockers", []) or []),
                entry_ready=bool(getattr(_runtime_state, "last_entry_eligible", False)),
            )
            _runtime_state.router_board = router.leaderboard()
        saved = {}
        for field in _SYMBOL_RUNTIME_FIELDS:
            if hasattr(_runtime_state, field):
                saved[field] = deepcopy(getattr(_runtime_state, field))
        _runtime_state.symbol_runtime_state[symbol] = saved
    except Exception:
        pass
    return result


__all__ = ["handle_tick"]

# NEXORA_ANTICHURN_APPLIED_v2
