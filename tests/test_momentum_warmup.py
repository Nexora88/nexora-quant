from app.decision import build_decision
from app.events import utc_now
from app.strategy import MarketAnalysis


def _analysis(**kwargs):
    base = dict(
        mid=100.0, spread_bps=2.0, imbalance=0.7, momentum_bps=0.0,
        trend="up", distance_to_target_pct=None, target_bias="none",
        score=0.7, reasons=["w_obi=0.5"], created_at=utc_now(),
        weighted_obi=0.45, micro_price=100.1, micro_premium_bps=2.0,
        ou_zscore=None, mean_reversion_signal="none", regime="trend",
        momentum_1m_bps=8.0, momentum_5m_bps=8.0,
    )
    base.update(kwargs)
    return MarketAnalysis(**base)


def test_block_entries_until_both_momentum_windows_are_warm():
    d = build_decision(
        analysis=_analysis(momentum_1m_bps=None, momentum_5m_bps=None),
        entry_min_score=0.5,
    )
    assert d.action == "block"
    assert "momentum_history_warmup" in d.blockers
