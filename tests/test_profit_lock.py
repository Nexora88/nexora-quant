from app.profit_lock import net_profit_lock_reason


def test_profit_lock_exits_when_net_peak_giveback_breaches_floor():
    reason = net_profit_lock_reason(
        bid=100.20, average_entry=100.0, peak_price=100.80,
        fee_rate=0.001, slippage_bps_per_side=2.0,
        momentum_1m_bps=-1.0, momentum_5m_bps=1.0,
        trade_flow=None, book_flow=None,
    )
    assert reason == "trailing_stop"


def test_profit_lock_requires_two_independent_reversal_groups():
    common = dict(
        bid=100.55, average_entry=100.0, peak_price=100.80,
        fee_rate=0.001, slippage_bps_per_side=2.0,
        momentum_1m_bps=-8.0, momentum_5m_bps=-2.0,
        trade_flow={"ready": True, "age_seconds": 0.0, "delta_ratio": -0.3},
        book_flow={"ready": False, "pressure": -0.5},
    )
    assert net_profit_lock_reason(**common) == "momentum_reversal"


def test_single_red_candle_or_one_flow_signal_does_not_exit():
    reason = net_profit_lock_reason(
        bid=100.55, average_entry=100.0, peak_price=100.80,
        fee_rate=0.001, slippage_bps_per_side=2.0,
        momentum_1m_bps=-8.0, momentum_5m_bps=1.0,
        trade_flow={"ready": True, "age_seconds": 0.0, "delta_ratio": -0.3},
        book_flow={"ready": False, "pressure": 0.0},
    )
    assert reason is None


def test_profit_lock_does_not_arm_before_all_in_cost_buffer():
    reason = net_profit_lock_reason(
        bid=100.20, average_entry=100.0, peak_price=100.30,
        fee_rate=0.001, slippage_bps_per_side=2.0,
        momentum_1m_bps=0.0, momentum_5m_bps=0.0,
        trade_flow=None, book_flow=None,
    )
    assert reason is None


def test_higher_fees_raise_profit_lock_activation_and_exit_floor():
    low_cost = net_profit_lock_reason(
        bid=100.85, average_entry=100.0, peak_price=101.30,
        fee_rate=0.0005, slippage_bps_per_side=1.0,
        momentum_1m_bps=0.0, momentum_5m_bps=0.0,
        trade_flow=None, book_flow=None,
    )
    high_cost = net_profit_lock_reason(
        bid=100.85, average_entry=100.0, peak_price=101.30,
        fee_rate=0.002, slippage_bps_per_side=4.0,
        momentum_1m_bps=0.0, momentum_5m_bps=0.0,
        trade_flow=None, book_flow=None,
    )
    assert low_cost is None
    assert high_cost == "trailing_stop"
