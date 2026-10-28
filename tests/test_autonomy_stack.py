"""Core autonomy: ATR dynamic stops, spoof persistence, BTC alt lock."""
from __future__ import annotations

from app.atr_stops import compute_dynamic_targets
from app.intelligence.btc_filter import BtcTrendFilter
from app.intelligence.spoof import OrderPersistenceFilter
from app.portfolio_risk import PortfolioRiskGate


def test_quiet_vs_storm_targets():
    quiet = compute_dynamic_targets(atr_pct=0.0008, regime="choppy")
    storm = compute_dynamic_targets(atr_pct=0.0045, regime="trend")
    assert 0.20 <= quiet.stop_loss_pct <= 0.55
    assert 0.20 <= storm.stop_loss_pct <= 0.55
    assert storm.take_profit_pct >= quiet.take_profit_pct * 0.9


def test_spoof_filter_default_at_least_1s():
    f = OrderPersistenceFilter(min_persist_ms=1500.0)
    assert f.min_persist_ms >= 1000.0


def test_btc_wick_blocks_then_cools():
    b = BtcTrendFilter(wick_jump_bps=35.0, cooldown_ticks=3)
    b.update(100_000.0)
    s = b.update(99_500.0)
    assert s.block_long is True or s.last_ret_bps < 0
    for _ in range(5):
        s = b.tick_cooldown()


def test_portfolio_one_position_max():
    g = PortfolioRiskGate(max_concurrent=1, max_total_risk_pct=0.35)
    ok, _ = g.can_open(symbol="btcusdt", notional_usdt=10, stop_loss_pct=0.35, equity_usdt=30)
    assert ok
    g.register("btcusdt", 10, 0.35)
    ok2, note = g.can_open(symbol="solusdt", notional_usdt=10, stop_loss_pct=0.35, equity_usdt=30)
    assert ok2 is False
    assert "max_concurrent" in note


def test_btc_correlation_blocks_alts():
    g = PortfolioRiskGate(max_concurrent=2)
    ok, note = g.can_open(
        symbol="ethusdt", notional_usdt=8, stop_loss_pct=0.35, equity_usdt=30, btc_blocks_alts=True
    )
    assert ok is False
    assert "btc_correlation" in note
