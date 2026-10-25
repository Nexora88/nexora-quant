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
