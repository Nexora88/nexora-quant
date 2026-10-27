from __future__ import annotations

from app.atr_stops import AtrTracker, compute_dynamic_targets
from app.portfolio_risk import PortfolioRiskGate


def test_atr_expands_stop_in_vol():
    quiet = compute_dynamic_targets(atr_pct=0.001, regime="choppy")
    hot = compute_dynamic_targets(atr_pct=0.004, regime="trend")
    assert 0.20 <= quiet.stop_loss_pct <= 0.55
    assert 0.20 <= hot.stop_loss_pct <= 0.55


def test_atr_tracker_updates():
    a = AtrTracker(period=10)
    for px in [100, 100.1, 99.9, 100.2, 100.0, 100.3]:
        a.update(px)
    assert a.atr_pct >= 0


def test_portfolio_blocks_second_position():
    g = PortfolioRiskGate(max_total_risk_pct=0.35, max_concurrent=1)
    ok, _ = g.can_open(symbol="btcusdt", notional_usdt=20, stop_loss_pct=0.35, equity_usdt=30)
    assert ok
    g.register("btcusdt", 20, 0.35)
    ok2, note = g.can_open(symbol="ethusdt", notional_usdt=20, stop_loss_pct=0.35, equity_usdt=30)
    assert ok2 is False
    assert "max_concurrent" in note


def test_portfolio_btc_lock_alts():
    g = PortfolioRiskGate(max_concurrent=2)
    ok, note = g.can_open(
        symbol="solusdt", notional_usdt=10, stop_loss_pct=0.35, equity_usdt=30, btc_blocks_alts=True
    )
    assert ok is False
    assert "btc_correlation" in note


def test_size_for_budget_shrinks():
    g = PortfolioRiskGate(max_total_risk_pct=0.35, max_concurrent=2)
    n = g.size_for_budget(equity_usdt=30, stop_loss_pct=0.35, desired_usdt=100, symbol="btcusdt")
    assert n <= 30 + 1e-6
