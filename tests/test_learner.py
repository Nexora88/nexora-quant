from app.intelligence.learner import OnlineLearner


def test_learner_raises_bar_after_losses():
    L = OnlineLearner(window=10, base_entry_min=0.35)
    base = L.entry_min_score
    for _ in range(8):
        L.record_trade(-1.0, regime="trend")
    assert L.entry_min_score >= base
    assert L.size_bias <= 1.0


def test_learner_prefers_winning_regime():
    L = OnlineLearner(window=20, base_entry_min=0.35)
    for _ in range(5):
        L.record_trade(1.0, regime="range")
    for _ in range(5):
        L.record_trade(-1.0, regime="trend")
    assert L.prefer_regime == "range"
    assert L.allows_regime("range")
