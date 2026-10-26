from app.intelligence.learner import OnlineLearner


def test_learner_raises_bar_after_losses():
    L = OnlineLearner(window=10, base_entry_min=0.35)
    base = L.entry_min_score
    for _ in range(8):
        L.record_trade(-1.0, regime="trend")
    assert L.entry_min_score >= base
    assert L.size_bias <= 1.0
    assert L.growth_mode == "protect"


def test_learner_grow_mode_after_wins():
    L = OnlineLearner(window=20, base_entry_min=0.35)
    for _ in range(10):
        L.record_trade(1.0, regime="range", reason="take_profit")
    assert L.growth_mode == "grow"
    assert L.size_bias >= 1.0


def test_learner_persist_roundtrip():
    L = OnlineLearner(window=10, base_entry_min=0.35)
    L.record_trade(0.5, regime="trend", reason="trailing_stop")
    L.record_trade(-0.2, regime="trend")
    blob = L.export_state()
    L2 = OnlineLearner(window=10, base_entry_min=0.35)
    L2.load_state(blob)
    assert L2.to_dict()["trades"] == 2
