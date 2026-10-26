from app.intelligence.learner import OnlineLearner


def test_learner_protect_after_losses():
    L = OnlineLearner(window=10, base_entry_min=0.32)
    base = L.entry_min_score
    for _ in range(8):
        L.record_trade(-1.0, regime="trend")
    assert L.entry_min_score >= base
    assert L.growth_mode == "protect"
    assert L.compound_fraction <= 0.85


def test_learner_compound_grow():
    L = OnlineLearner(window=20, base_entry_min=0.32)
    for _ in range(10):
        L.record_trade(0.15, regime="range", reason="take_profit")
    assert L.growth_mode == "grow"
    assert L.compound_fraction >= 0.85
    assert L.tp_scale <= 1.1


def test_learner_persist_roundtrip():
    L = OnlineLearner(window=10)
    L.record_trade(0.5, regime="trend", reason="take_profit")
    L.record_trade(-0.1, regime="trend")
    blob = L.export_state()
    L2 = OnlineLearner(window=10)
    L2.load_state(blob)
    assert L2.to_dict()["trades"] == 2
    assert "compound" in blob
