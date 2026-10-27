"""Gaps: aggressive stop slippage, dynamic fees, macro regime pause."""
from __future__ import annotations

import pytest

from app.analytics.regime import MarketRegime, RegimeClassifier
from app.config import Settings
from app.expectancy import asymmetric_expectancy, breakeven_win_rate, effective_stop_loss_pct
from app.fees import FeeSchedule, schedule_from_settings
from app.simulation import ExecutionSimulator, symbol_visible_liquidity_usdt
from app.strategy import MarketAnalysis, entry_signal_from_analysis
from app.events import utc_now


def test_symbol_visible_liquidity_thinner_for_alts():
    assert symbol_visible_liquidity_usdt("solusdt") < symbol_visible_liquidity_usdt("btcusdt")
    assert symbol_visible_liquidity_usdt("bnbusdt") < symbol_visible_liquidity_usdt("ethusdt")


def test_stop_stress_increases_sell_slippage():
    sim = ExecutionSimulator(
        slippage_bps=0,
        latency_ms=0,
        seed=42,
        impact_coefficient=0.2,
        stop_stress_multiplier=2.5,
        stop_tail_bps=0.0,
        default_visible_liquidity_usdt=10_000.0,
    )
    calm = sim.fill(side="sell", reference_price=100.0, quantity=1.0, stress=False)
    panic = sim.fill(side="sell", reference_price=100.0, quantity=1.0, stress=True)
    assert panic.stress_applied
    assert not calm.stress_applied
    assert panic.slippage_bps > calm.slippage_bps
    # Stressed fill should be worse for seller (lower price).
    assert panic.fill_price < calm.fill_price


def test_effective_stop_with_slippage_worsens_breakeven():
    base = breakeven_win_rate(take_profit_pct=1.20, stop_loss_pct=0.35, fee_rate=0.001)
    stressed = breakeven_win_rate(
        take_profit_pct=1.20, stop_loss_pct=0.35, fee_rate=0.001, extra_slippage_pct=0.15,
    )
    assert effective_stop_loss_pct(stop_loss_pct=0.35, extra_slippage_pct=0.15) == pytest.approx(0.50)
    assert stressed > base


def test_bnb_discount_cuts_taker_about_25pct():
    plain = FeeSchedule(vip_level=0, use_bnb_discount=False)
    disc = FeeSchedule(vip_level=0, use_bnb_discount=True)
    assert disc.taker_rate() == pytest.approx(plain.taker_rate() * 0.75)
    assert disc.effective_round_trip() < plain.effective_round_trip()


def test_vip_lowers_fees():
    v0 = FeeSchedule(vip_level=0)
    v3 = FeeSchedule(vip_level=3)
    assert v3.taker_rate() < v0.taker_rate()


def test_schedule_from_settings_override():
    s = schedule_from_settings(fee_rate=0.0008, vip_level=0, use_bnb_discount=False)
    assert s.taker_rate() == pytest.approx(0.0008)


def test_settings_effective_fee_bnb():
    s = Settings(fee_rate=0.001, fee_vip_level=0, fee_use_bnb_discount=True).validate()
    assert s.effective_fee_rate() == pytest.approx(0.00075)


def test_wick_triggers_stressed_pause():
    clf = RegimeClassifier(window=40, wick_jump_bps=30.0, wick_cooldown=5)
    mid = 100.0
    for _ in range(20):
        snap = clf.update(mid=mid, spread_bps=3.0, volume_proxy=1.0)
        mid *= 1.0001
    # Liquidation-style spike
    snap = clf.update(mid=mid * 1.01, spread_bps=4.0, volume_proxy=2.0)
    assert snap.regime == MarketRegime.STRESSED
    assert snap.pause_entries is True
    assert snap.wick_score > 0


def test_choppy_flip_rate_pauses():
    clf = RegimeClassifier(window=40, chop_flip_ratio=0.5, high_vol_bps=80.0)
    mid = 100.0
    for i in range(30):
        # Alternate up/down small moves → high flip ratio, low vol
        mid *= 1.0005 if i % 2 == 0 else (1 / 1.0005)
        snap = clf.update(mid=mid, spread_bps=2.0, volume_proxy=1.0)
    assert snap.regime in (MarketRegime.CHOPPY, MarketRegime.RANGE, MarketRegime.STRESSED)
    if snap.regime == MarketRegime.CHOPPY:
        assert snap.pause_entries is True


def test_entry_blocked_on_choppy_regime():
    analysis = MarketAnalysis(
        mid=100.0,
        spread_bps=2.0,
        imbalance=0.8,
        momentum_bps=10.0,
        trend="up",
        distance_to_target_pct=0.0,
        target_bias="none",
        score=0.9,
        reasons=["w_obi=0.8"],
        created_at=utc_now(),
        regime="choppy",
    )
    assert entry_signal_from_analysis(analysis, min_score=0.55) is None


def test_expectancy_improves_with_lower_fees():
    high = asymmetric_expectancy(
        win_rate=0.40, take_profit_pct=1.20, stop_loss_pct=0.35, fee_rate=0.001,
    )
    low = asymmetric_expectancy(
        win_rate=0.40, take_profit_pct=1.20, stop_loss_pct=0.35, fee_rate=0.00075,
    )
    assert low > high
