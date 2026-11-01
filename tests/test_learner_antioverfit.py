from __future__ import annotations

from app.intelligence.learner import OnlineLearner


def test_frozen_learner_does_not_move_gates():
    L = OnlineLearner(window=10, base_entry_min=0.32, frozen=True)
    base = L.entry_min_score
    for _ in range(8):
        L.record_trade(-1.0, regime="trend")
    assert L.entry_min_score == base
    assert L.growth_mode == "rebuild"
    assert L.to_dict()["frozen"] is True


def test_anomaly_skip_does_not_yank_weights():
    L = OnlineLearner(window=20, base_entry_min=0.32, anomaly_z=2.5)
    for _ in range(8):
        L.record_trade(0.05, regime="range", reason="take_profit")
    before = L.entry_min_score
    # One extreme whale-style PnL should not rewrite policy
    L.record_trade(50.0, regime="range", reason="wick")
    assert L.to_dict()["anomaly_skips"] >= 1
    assert abs(L.entry_min_score - before) < 0.08


def test_production_snapshot_restore():
    L = OnlineLearner(window=10, base_entry_min=0.32)
    for _ in range(6):
        L.record_trade(0.2, regime="trend", reason="take_profit")
    L.snapshot_production()
    moved = L.entry_min_score
    L.record_trade(-2.0, regime="choppy")
    L.restore_production()
    assert abs(L.entry_min_score - moved) < 1e-9
