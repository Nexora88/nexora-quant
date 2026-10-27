"""Spoof persistence, BTC lock, pessimistic expectancy, alert hooks."""
from __future__ import annotations

from app.expectancy import (
    asymmetric_expectancy,
    breakeven_win_rate,
    effective_stop_loss_pct,
    pessimistic_slippage_pct,
)
from app.intelligence.btc_filter import BtcTrendFilter
from app.intelligence.spoof import OrderPersistenceFilter
from app.risk import RiskManager


def test_spoof_marks_flash_levels_as_transient():
    f = OrderPersistenceFilter(min_persist_ms=1000.0, price_tick=0.1)
    r1 = f.update([(100.0, 5.0)], [(100.1, 5.0)], now_ms=0.0)
    assert r1.stable_bid_usdt == 0.0
    assert r1.transient_bid_usdt > 0
    r2 = f.update([(100.0, 5.0)], [(100.1, 5.0)], now_ms=1500.0)
    assert r2.stable_bid_usdt > 0
    assert r2.spoof_score < r1.spoof_score or r2.stable_bid_usdt >= r1.transient_bid_usdt


def test_btc_wick_blocks_then_cools():
    bf = BtcTrendFilter(wick_jump_bps=30.0, cooldown_ticks=3)
    bf.update(100.0)
    s = bf.update(99.6)
    assert s.block_long is True
    s2 = bf.tick_cooldown()
    assert s2.cooldown_left <= s.cooldown_left


def test_pessimistic_slip_worse_on_sol_than_btc():
    assert pessimistic_slippage_pct("solusdt") > pessimistic_slippage_pct("btcusdt")
    eff = effective_stop_loss_pct(stop_loss_pct=0.35, symbol="solusdt", use_pessimistic=True)
    assert eff >= 0.50


def test_breakeven_rises_with_pessimistic_slip():
    base = breakeven_win_rate(take_profit_pct=1.20, stop_loss_pct=0.35, fee_rate=0.001)
    bad = breakeven_win_rate(
        take_profit_pct=1.20,
        stop_loss_pct=0.35,
        fee_rate=0.001,
        extra_slippage_pct=pessimistic_slippage_pct("solusdt", stress=True),
    )
    assert bad > base


def test_bnb_fee_improves_expectancy():
    high = asymmetric_expectancy(win_rate=0.4, take_profit_pct=1.2, stop_loss_pct=0.35, fee_rate=0.001)
    low = asymmetric_expectancy(win_rate=0.4, take_profit_pct=1.2, stop_loss_pct=0.35, fee_rate=0.00075)
    assert low > high


def test_kill_switch_sets_flag():
    rm = RiskManager(
        max_order_size_usdt=25,
        max_daily_loss_usdt=5,
        max_consecutive_losses=3,
        max_spread_bps=20,
        max_data_age_seconds=8,
    )
    rm.activate_kill_switch("test")
    assert rm.kill_switch is True
    assert rm.kill_switch_reason == "test"
