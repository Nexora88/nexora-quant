from __future__ import annotations

from app.intelligence.learner import OnlineLearner


def test_unlabeled_market_observations_do_not_drift_live_threshold():
    L = OnlineLearner(base_entry_min=0.30, min_entry=0.20, max_entry=0.65)
    before = L.entry_min_score
    for _ in range(500):
        L.observe_market(
            score=0.45, regime="trend", flow_pressure=0.3, flow_ready=True, in_position=False
        )
    assert L.entry_min_score == before
    assert "waiting_for_closed_trade" in L.to_dict()["note"]


def test_record_trade_grow_mode():
    L = OnlineLearner(base_entry_min=0.30, window=10)
    for _ in range(6):
        L.record_trade(0.15, regime="trend", reason="take_profit")
    assert L.growth_mode in ("grow", "rebuild")
    d = L.to_dict()
    assert d.get("lifetime_trades", 0) >= 1 or d.get("trades", 0) >= 1
