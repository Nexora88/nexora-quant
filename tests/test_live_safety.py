import pytest

from app.live import LiveExecutor
from app.risk import RiskManager


def test_live_executor_is_disabled_fail_closed():
    with pytest.raises(RuntimeError, match="LiveExecutor is disabled"):
        LiveExecutor(object(), symbol="BTCUSDT", fee_rate=0.001)


def test_stale_or_disconnected_market_data_blocks_new_orders():
    risk = RiskManager(
        max_order_size_usdt=50, max_daily_loss_usdt=25,
        max_consecutive_losses=3, max_spread_bps=20,
        max_data_age_seconds=5,
    )
    decision = risk.evaluate_entry(
        notional_usdt=10, available_cash=100, bid=100, ask=100.1,
        data_age_seconds=None,
    )
    assert not decision.allowed
    assert "stale" in decision.reason.lower()
    risk.activate_kill_switch("connection lost")
    blocked = risk.evaluate_entry(
        notional_usdt=10, available_cash=100, bid=100, ask=100.1,
        data_age_seconds=0.1,
    )
    assert not blocked.allowed
    assert "connection lost" in blocked.reason
