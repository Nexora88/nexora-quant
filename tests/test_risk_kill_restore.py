from app.risk import RiskManager


def test_paper_kill_switch_survives_state_restore():
    risk = RiskManager(
        max_order_size_usdt=25,
        max_daily_loss_usdt=2,
        max_consecutive_losses=4,
        max_spread_bps=22,
        max_data_age_seconds=8,
    )
    risk.restore({
        "kill_switch": True,
        "kill_switch_reason": "Consecutive-loss limit reached",
        "consecutive_losses": 4,
        "realized_pnl_today": -0.32,
        "day_utc": "2026-11-16",
    })
    assert risk.kill_switch is True
    assert risk.kill_switch_reason == "Consecutive-loss limit reached"
    decision = risk.evaluate_entry(
        notional_usdt=10, available_cash=100, bid=99.9, ask=100.0,
        data_age_seconds=0.1,
    )
    assert decision.allowed is False
