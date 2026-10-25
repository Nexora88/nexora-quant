from app.intelligence.whale import WhaleTracker
from app.intelligence.noise import NoiseFilter


def test_whale_detects_persistent_bid_wall():
    w = WhaleTracker(multiple=3.0, persist_ticks=3)
    bids = [(100.0, 1.0), (99.9, 1.0), (99.8, 50.0)]
    asks = [(100.1, 1.0), (100.2, 1.0)]
    sig = None
    for _ in range(5):
        sig = w.update(bids, asks, 100.05)
    assert sig is not None
    assert sig.side == "bid"
    assert sig.strength > 0


def test_noise_flags_oscillation():
    n = NoiseFilter(window=10, min_stability=0.6)
    scores = [0.8, -0.7, 0.75, -0.6, 0.7, -0.8, 0.6, -0.5, 0.55, -0.9]
    last = None
    for s in scores:
        last = n.update(s)
    assert last is not None
    assert last.noisy is True
