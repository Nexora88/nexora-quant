from app.state import RuntimeState


class EquityExecutor:
    def __init__(self, equity):
        self.equity = equity

    def snapshot(self, mark=None):
        return {"equity_usdt": self.equity}


def test_session_metrics_cover_all_closed_trades_and_exit_reasons():
    state = RuntimeState()
    for pnl, reason in [(1.0, "take_profit"), (-0.5, "stop_loss"), (0.25, "take_profit")]:
        state.record_fill({
            "side": "sell",
            "pnl_usdt": pnl,
            "fee_usdt": 0.01,
            "accounting_complete": True,
            "reason": reason,
        })
    metrics = state.session_expectancy()
    assert metrics["n"] == 3
    assert metrics["sum_pnl_usdt"] == 0.75
    assert metrics["expectancy_usdt"] == 0.25
    assert metrics["win_rate"] == 2 / 3
    assert state.session_exit_reasons == {"take_profit": 2, "stop_loss": 1}


def test_observed_drawdown_tracks_peak_to_trough_not_only_current_dd():
    state = RuntimeState()
    state.executor = EquityExecutor(100.0)
    state.sample_equity()
    state.executor.equity = 92.0
    state.sample_equity()
    state.executor.equity = 98.0
    state.sample_equity()
    snapshot = state.snapshot()
    assert snapshot["max_drawdown_usdt"] == 8.0
    assert snapshot["max_drawdown_pct_observed"] == 8.0
