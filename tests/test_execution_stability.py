from app.paper import PaperExecutor
from app.risk import RiskManager
from app.simulation import ExecutionSimulator


def make_risk():
    return RiskManager(
        max_order_size_usdt=50,
        max_daily_loss_usdt=25,
        max_consecutive_losses=3,
        max_spread_bps=20,
        max_data_age_seconds=5,
    )


def test_daily_loss_rolls_over_utc_day_but_keeps_consecutive_loss_streak():
    risk = make_risk()
    risk.rollover_day("2026-10-25")
    risk.record_closed_trade(-26)
    assert risk.kill_switch
    assert risk.realized_pnl_today == -26
    assert risk.rollover_day("2026-10-26")
    assert risk.realized_pnl_today == 0
    assert not risk.kill_switch
    assert risk.consecutive_losses == 1
    assert not risk.rollover_day("2026-10-26")


def test_daily_rollover_does_not_clear_other_kill_switches():
    risk = make_risk()
    risk.rollover_day("2026-10-25")
    risk.activate_kill_switch("Consecutive-loss limit reached")
    risk.rollover_day("2026-10-26")
    assert risk.kill_switch
    assert risk.kill_switch_reason == "Consecutive-loss limit reached"


def test_partial_sell_preserves_remaining_position_and_cost_basis():
    account = PaperExecutor(1000, 0.001)
    account.buy(notional_usdt=100, price=100, reason="test")
    original_qty = account.base_quantity
    trade = account.sell_quantity(quantity=original_qty / 2, price=110, reason="take_profit")
    assert trade is not None
    assert account.base_quantity == original_qty / 2
    assert account.average_entry_price == 100
    assert account.cash_usdt > 900


def test_partial_realized_pnl_counts_daily_loss_but_not_closed_trade_streak():
    risk = make_risk()
    risk.rollover_day("2026-10-25")
    risk.record_realized_pnl(-2, position_closed=False)
    assert risk.realized_pnl_today == -2
    assert risk.consecutive_losses == 0


def test_partial_fill_simulation_is_reproducible_and_adverse():
    first = ExecutionSimulator(
        slippage_bps=4, latency_ms=100, partial_fill_probability=1, seed=23
    ).fill(side="buy", reference_price=100, quantity=2)
    second = ExecutionSimulator(
        slippage_bps=4, latency_ms=100, partial_fill_probability=1, seed=23
    ).fill(side="buy", reference_price=100, quantity=2)
    assert first == second
    assert 0 < first.filled_quantity < first.requested_quantity
    assert first.fill_price >= 100
    assert first.latency_ms >= 0


def test_restore_rejects_inconsistent_position_and_entry_price():
    account = PaperExecutor(1000, 0.001)
    snapshot = account.snapshot()
    snapshot["base_quantity"] = 0.1
    snapshot["average_entry_price"] = 0
    try:
        account.restore(snapshot)
    except ValueError as exc:
        assert "inconsistent" in str(exc)
    else:
        raise AssertionError("inconsistent restored position must be rejected")
