"""Fee / slippage / regime interaction smoke tests."""
from __future__ import annotations

from app.events import utc_now
from app.expectancy import asymmetric_expectancy
from app.strategy import MarketAnalysis, entry_signal_from_analysis


def test_asymmetric_expectancy_positive_at_design_rr():
    e = asymmetric_expectancy(
        win_rate=0.40, take_profit_pct=1.20, stop_loss_pct=0.35, fee_rate=0.001
    )
    assert e > 0


def test_entry_blocked_on_stressed_regime():
    analysis = MarketAnalysis(
        mid=100.0,
        spread_bps=2.0,
        imbalance=0.8,
        momentum_bps=10.0,
        trend="up",
        distance_to_target_pct=0.0,
        target_bias="none",
        score=0.9,
        reasons=["w_obi=0.8"],
        created_at=utc_now(),
        regime="stressed",
    )
    assert entry_signal_from_analysis(analysis, min_score=0.55) is None


def test_entry_blocked_on_choppy_regime():
    # Weak choppy stays blocked; strong score may pass with raised threshold.
    weak = MarketAnalysis(
        mid=100.0, spread_bps=2.0, imbalance=0.8, momentum_bps=10.0, trend="up",
        distance_to_target_pct=0.0, target_bias="none", score=0.58,
        reasons=["w_obi=0.8"], created_at=utc_now(), regime="choppy",
    )
    assert entry_signal_from_analysis(weak, min_score=0.55) is None
    strong = MarketAnalysis(
        mid=100.0, spread_bps=2.0, imbalance=0.8, momentum_bps=10.0, trend="up",
        distance_to_target_pct=0.0, target_bias="none", score=0.90,
        reasons=["w_obi=0.8"], created_at=utc_now(), regime="choppy",
    )
    sig = entry_signal_from_analysis(strong, min_score=0.55)
    assert sig is not None and sig.action == "buy"
