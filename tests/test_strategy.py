import pytest

from app.strategy import (
    PriceWindow,
    analyze_market,
    entry_signal_from_analysis,
    evaluate_imbalance,
    exit_reason,
    imbalance_strength,
)


def test_signal_only_above_threshold():
    assert evaluate_imbalance(7, 3, 0.70) is not None
    assert evaluate_imbalance(5, 5, 0.70) is None


def test_imbalance_strength():
    assert imbalance_strength(7, 3) == 0.7


def test_composite_entry_and_target():
    window = PriceWindow()
    for p in range(100, 120):
        window.push(float(p))
    analysis = analyze_market(
        bid=119,
        ask=119.2,
        bid_qty=10,
        ask_qty=2,
        price_window=window,
        imbalance_threshold=0.65,
        target_price=130,
    )
    assert analysis.score > 0
    assert analysis.target_bias == "approach_buy"
    sig = entry_signal_from_analysis(analysis, min_score=0.4)
    assert sig is not None and sig.action == "buy"


def test_analysis_uses_seeded_candle_momentum_overrides_during_tick_warmup():
    window = PriceWindow()
    analysis = analyze_market(
        bid=100.0, ask=100.02, bid_qty=20, ask_qty=10,
        price_window=window, imbalance_threshold=0.65,
        momentum_1m_override_bps=12.0, momentum_5m_override_bps=28.0,
    )
    assert analysis.momentum_1m_bps == pytest.approx(12.0)
    assert analysis.momentum_5m_bps == pytest.approx(28.0)


def test_analysis_uses_supplied_event_time_for_replay_momentum():
    window = PriceWindow(maxlen=1200)
    common = {
        "bid_qty": 10,
        "ask_qty": 10,
        "price_window": window,
        "imbalance_threshold": 0.70,
    }
    for price, timestamp in ((100.0, 1_000.0), (101.0, 1_060.0)):
        analyze_market(
            bid=price - 0.01, ask=price + 0.01, timestamp=timestamp, **common,
        )

    analysis = analyze_market(
        bid=102.0 - 0.01, ask=102.0 + 0.01,
        timestamp=1_300.0, **common,
    )
    assert analysis.momentum_1m_bps == pytest.approx((102.0 / 101.0 - 1) * 10_000)
    assert analysis.momentum_5m_bps == pytest.approx((102.0 / 100.0 - 1) * 10_000)


def test_trailing_stop_does_not_arm_on_tiny_gross_profit():
    # A tiny uptick cannot pay round-trip fees plus stressed exit slippage.
    assert exit_reason(
        bid=100.05,
        average_entry=100.0,
        take_profit_pct=0.65,
        stop_loss_pct=0.22,
        trailing_stop_pct=0.14,
        peak_price=100.20,
        target_price=None,
    ) is None


def test_trailing_stop_arms_only_after_cost_buffer():
    assert exit_reason(
        bid=100.45,
        average_entry=100.0,
        take_profit_pct=0.65,
        stop_loss_pct=0.22,
        trailing_stop_pct=0.14,
        peak_price=100.60,
        target_price=None,
    ) == "trailing_stop"


def test_exit_priority_stop_and_target():
    assert exit_reason(
        bid=99,
        average_entry=100,
        take_profit_pct=2,
        stop_loss_pct=0.5,
        trailing_stop_pct=0.3,
        peak_price=100,
        target_price=110,
    ) == "stop_loss"
    assert exit_reason(
        bid=111,
        average_entry=100,
        take_profit_pct=20,
        stop_loss_pct=5,
        trailing_stop_pct=0,
        peak_price=100,
        target_price=110,
    ) == "target_price"
    assert exit_reason(
        bid=104,
        average_entry=100,
        take_profit_pct=5,
        stop_loss_pct=5,
        trailing_stop_pct=0.5,
        peak_price=106,
        target_price=None,
    ) == "trailing_stop"
