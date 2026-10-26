"""Asymmetric reward/risk and expectancy math."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.expectancy import asymmetric_expectancy, breakeven_win_rate, reward_risk_ratio


def test_reward_risk_default_asymmetric():
    assert reward_risk_ratio(take_profit_pct=1.20, stop_loss_pct=0.35) == pytest.approx(1.20 / 0.35)


def test_breakeven_below_forty_with_strong_rr():
    p = breakeven_win_rate(take_profit_pct=1.20, stop_loss_pct=0.35, fee_rate=0.001)
    assert p < 0.40


def test_expectancy_positive_at_40pct_with_asymmetry():
    e = asymmetric_expectancy(
        win_rate=0.40,
        take_profit_pct=1.20,
        stop_loss_pct=0.35,
        fee_rate=0.001,
    )
    assert e > 0


def test_config_rejects_poor_rr():
    with pytest.raises(ValueError, match="MIN_REWARD_RISK_RATIO"):
        Settings(
            take_profit_pct=0.30,
            stop_loss_pct=0.50,
            min_reward_risk_ratio=2.0,
        ).validate()


def test_config_accepts_asymmetric_defaults():
    s = Settings(take_profit_pct=1.20, stop_loss_pct=0.35, min_reward_risk_ratio=2.0).validate()
    assert s.take_profit_pct / s.stop_loss_pct >= 2.0


def test_watch_symbols_dedupe():
    s = Settings(symbol="btcusdt", symbols_raw="ethusdt, btcusdt, SOLUSDT").validate()
    assert s.watch_symbols()[0] == "btcusdt"
    assert "ethusdt" in s.watch_symbols()
    assert "solusdt" in s.watch_symbols()
    assert len(s.watch_symbols()) == 3
