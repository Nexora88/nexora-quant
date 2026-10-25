from app.strategy import evaluate_imbalance, imbalance_strength

def test_bid_imbalance_strength():
    assert imbalance_strength(7, 3) == 0.7

def test_signal_only_above_threshold():
    assert evaluate_imbalance(8, 2, 0.7) is not None
    assert evaluate_imbalance(6, 4, 0.7) is None

def test_zero_quantities_are_neutral():
    assert imbalance_strength(0, 0) == 0.5
