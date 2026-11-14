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

# NOTE: full body continues in repo — this push was truncated; use local restore
