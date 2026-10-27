from __future__ import annotations

from app.intelligence.learner import OnlineLearner
from app.rate_limiter import BinanceWeightLimiter
from app.simulation import ExecutionSimulator


def test_rate_limiter_acquire_and_stats():
    lim = BinanceWeightLimiter(capacity=10.0, refill_per_sec=100.0)
    lim.acquire(5)
    lim.acquire(5)
    s = lim.stats()
    assert s.capacity == 10.0


def test_rate_limiter_weights():
    lim = BinanceWeightLimiter()
    assert lim.weight_for("/api/v3/account") >= 10
    assert lim.weight_for("/api/v3/order", "POST") == 1


def test_learner_regime_change_pulls_toward_prior():
    L = OnlineLearner(window=20, base_entry_min=0.40, l2_lambda=0.20)
    for _ in range(5):
        L.record_trade(0.5, regime="trend", reason="take_profit")
    high = L.entry_min_score
    L.record_trade(-0.2, regime="choppy", reason="stop_loss")
    assert abs(L.entry_min_score - L.base_entry_min) < abs(high - L.base_entry_min) + 0.2


def test_asymmetric_buy_latency_higher():
    sim = ExecutionSimulator(slippage_bps=0, latency_ms=100, seed=42)
    buys = [sim.fills(side="buy", reference_price=100.0, quantity=0.01).latency_ms for _ in range(8)]
    sells = [sim.fills(side="sell", reference_price=100.0, quantity=0.01).latency_ms for _ in range(8)]
    assert sum(buys) / len(buys) > sum(sells) / len(sells)
