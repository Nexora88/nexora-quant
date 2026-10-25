from app.risk import RiskManager

def manager():
    return RiskManager(max_order_size_usdt=50, max_daily_loss_usdt=25, max_consecutive_losses=3, max_spread_bps=20, max_data_age_seconds=5)

def test_allows_safe_paper_entry():
    decision = manager().evaluate_entry(notional_usdt=25, available_cash=100, bid=99.99, ask=100.00, data_age_seconds=0.2)
    assert decision.allowed

def test_blocks_stale_data():
    decision = manager().evaluate_entry(notional_usdt=25, available_cash=100, bid=99.99, ask=100.00, data_age_seconds=10)
    assert not decision.allowed and "stale" in decision.reason

def test_blocks_wide_spread():
    decision = manager().evaluate_entry(notional_usdt=25, available_cash=100, bid=99, ask=101, data_age_seconds=0.1)
    assert not decision.allowed

def test_loss_streak_activates_kill_switch():
    risk = manager()
    for _ in range(3):
        risk.record_closed_trade(-1)
    assert risk.kill_switch
