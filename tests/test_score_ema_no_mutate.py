"""Entry decision must use raw score; EMA is dashboard-only."""
from __future__ import annotations

from datetime import datetime, timezone

from app.state import RuntimeState
from app.strategy import MarketAnalysis


def _analysis(score: float) -> MarketAnalysis:
    return MarketAnalysis(
        mid=100.0,
        spread_bps=2.0,
        imbalance=0.6,
        momentum_bps=1.0,
        trend="up",
        distance_to_target_pct=None,
        target_bias="none",
        score=score,
        reasons=["test"],
        created_at=datetime.now(timezone.utc),
        weighted_obi=0.55,
        micro_premium_bps=0.5,
        regime="trend",
    )


def test_record_analysis_does_not_mutate_raw_score() -> None:
    st = RuntimeState()
    a = _analysis(0.90)
    st.record_analysis(a)
    assert a.score == 0.90  # raw preserved for entry
    assert st.last_analysis is not None
    assert st.last_analysis["score_raw"] == 0.90
    assert abs(float(st.score_ema) - 0.90) < 1e-9


def test_ema_smoothing_does_not_dilute_entry_object() -> None:
    st = RuntimeState()
    st.record_analysis(_analysis(0.20))
    a2 = _analysis(0.95)
    st.record_analysis(a2)
    assert a2.score == 0.95
    assert 0.20 < float(st.score_ema) < 0.95
