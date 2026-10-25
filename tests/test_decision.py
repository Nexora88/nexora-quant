from app.decision import build_decision
from app.events import utc_now
from app.strategy import MarketAnalysis


def _analysis(**kwargs):
    base = dict(
        mid=100.0,
        spread_bps=2.0,
        imbalance=0.7,
        momentum_bps=8.0,
        trend="up",
        distance_to_target_pct=None,
        target_bias="none",
        score=0.7,
        reasons=["w_obi=0.5", "mom_up=8bps"],
        created_at=utc_now(),
        weighted_obi=0.45,
        micro_price=100.1,
        micro_premium_bps=2.0,
        ou_zscore=None,
        mean_reversion_signal="none",
        regime="trend",
    )
    base.update(kwargs)
    return MarketAnalysis(**base)


def test_enter_long_when_edge():
    d = build_decision(analysis=_analysis(), entry_min_score=0.5)
    assert d.action == "enter_long"
    assert d.confidence > 0
    assert any(v.direction == "long" for v in d.votes)


def test_block_on_stressed_regime():
    d = build_decision(analysis=_analysis(regime="stressed", score=0.9), entry_min_score=0.5)
    assert d.action == "block"
    assert "regime_stressed" in d.blockers


def test_hold_when_in_position():
    d = build_decision(analysis=_analysis(), in_position=True)
    assert d.action == "hold"
