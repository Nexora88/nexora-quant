from datetime import datetime, timezone

from app.atr_stops import compute_dynamic_targets
from app.strategy import MarketAnalysis, PriceWindow, entry_signal_from_analysis, exit_reason


def _analysis(m1=None, m5=None):
    return MarketAnalysis(
        mid=100.0, spread_bps=1.0, imbalance=0.8, momentum_bps=10.0,
        trend="up", distance_to_target_pct=None, target_bias="none",
        score=0.9, reasons=["momentum"], created_at=datetime.now(timezone.utc),
        momentum_1m_bps=m1, momentum_5m_bps=m5,
    )


def test_price_window_tracks_real_elapsed_time_momentum():
    prices = PriceWindow(maxlen=1000)
    for second in range(301):
        prices.push(100.0 + second * 0.01, timestamp=float(second))
    assert prices.momentum_over(60) > 0
    assert prices.momentum_over(300) > 0


def test_price_window_does_not_fake_full_window_during_warmup():
    prices = PriceWindow()
    for second in range(20):
        prices.push(100.0 + second * 0.01, timestamp=float(second))
    assert prices.momentum_over(60) is None
    assert prices.momentum_over(300) is None


def test_spot_entry_rejects_confirmed_down_momentum():
    assert entry_signal_from_analysis(_analysis(m1=-4.0, m5=-8.0), min_score=0.2) is None


def test_exit_cuts_losing_position_on_multitimeframe_reversal():
    reason = exit_reason(
        bid=99.9, average_entry=100.0, take_profit_pct=0.6,
        stop_loss_pct=0.3, trailing_stop_pct=0.15, peak_price=100.0,
        target_price=None, momentum_1m_bps=-8.0, momentum_5m_bps=-3.0,
    )
    assert reason == "momentum_reversal"


def test_dynamic_target_covers_twice_all_in_round_trip_cost():
    targets = compute_dynamic_targets(
        atr_pct=0.0001, regime="range", fee_round_trip_pct=0.25,
    )
    assert targets.take_profit_pct >= 0.50
