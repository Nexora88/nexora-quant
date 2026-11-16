from app.state import RuntimeState


def test_incomplete_live_commission_is_not_counted_as_a_closed_pnl_sample():
    state = RuntimeState()
    state.record_fill({
        "side": "sell",
        "pnl_usdt": None,
        "fee_usdt": 0.01,
        "accounting_complete": False,
    })
    assert state.closed_trade_count == 0
    assert state.session_realized_pnl_usdt == 0
    assert state.session_expectancy()["n"] == 0

    state.record_fill({
        "side": "sell",
        "pnl_usdt": 0.25,
        "fee_usdt": 0.02,
        "accounting_complete": True,
    })
    assert state.closed_trade_count == 1
    assert state.session_expectancy()["n"] == 1
    assert state.session_expectancy()["expectancy_usdt"] == 0.25
