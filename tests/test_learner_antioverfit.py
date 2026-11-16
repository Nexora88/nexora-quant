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

def test_export_restore_preserves_exact_policy_weights_and_regime():
    source = OnlineLearner(window=20, base_entry_min=0.32)
    for _ in range(12):
        source.record_trade(0.2, regime="trend", reason="take_profit")
    source.observe_market(
        score=0.7, regime="range", flow_pressure=0.3, flow_ready=True,
    )
    saved = source.export_state()
    expected = (
        source.entry_min_score, source.size_bias, source.tp_scale,
        source.compound_fraction, source.growth_mode,
    )

    restored = OnlineLearner(window=20, base_entry_min=0.32)
    restored.load_state(saved)
    actual = (
        restored.entry_min_score, restored.size_bias, restored.tp_scale,
        restored.compound_fraction, restored.growth_mode,
    )
    assert actual == expected
    assert restored._last_regime == "range"


def test_restore_rejects_corrupt_non_finite_weights():
    learner = OnlineLearner()
    saved = learner.export_state()
    saved["entry_min"] = float("nan")
    try:
        learner.load_state(saved)
    except ValueError as exc:
        assert "non-finite" in str(exc)
    else:
        raise AssertionError("corrupt learner weights must be rejected")
