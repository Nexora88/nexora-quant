import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from app.build_info import source_fingerprint
from app.config import Settings


def test_invalid_mode_is_rejected():
    with pytest.raises(ValueError, match="paper' or 'live"):
        Settings(trading_mode="production").validate()


def test_live_without_keys_is_rejected():
    with pytest.raises(ValueError, match="BINANCE_API_KEY"):
        Settings(
            trading_mode="live",
            binance_api_key="",
            binance_api_secret="",
            binance_testnet=True,
        ).validate()


def test_mainnet_live_requires_confirmation():
    with pytest.raises(ValueError, match="LIVE_CONFIRM"):
        Settings(
            trading_mode="live",
            binance_api_key="k",
            binance_api_secret="s",
            binance_testnet=False,
            live_confirm="",
        ).validate()


def test_testnet_live_accepted_with_keys():
    s = Settings(
        trading_mode="live",
        binance_api_key="k",
        binance_api_secret="s",
        binance_testnet=True,
    ).validate()
    assert s.trading_mode == "live"
    assert s.binance_testnet is True


def test_mainnet_live_accepted_only_with_confirmation_and_go_live_stamp(tmp_path, monkeypatch):
    stamp = tmp_path / "GO_LIVE_OK"
    stamp.write_text(json.dumps({
        "ok": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "source_fingerprint": source_fingerprint(Path(__file__).resolve().parents[1]),
    }), encoding="utf-8")
    monkeypatch.setenv("GO_LIVE_STAMP_PATH", str(stamp))
    s = Settings(
        trading_mode="live",
        binance_api_key="k",
        binance_api_secret="s",
        binance_testnet=False,
        live_confirm="I_UNDERSTAND_REAL_MONEY",
    ).validate()
    assert s.trading_mode == "live"
    assert s.binance_testnet is False


def test_mainnet_live_rejects_missing_stamp_even_if_old_bypass_env_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("GO_LIVE_STAMP_PATH", str(tmp_path / "missing-stamp"))
    monkeypatch.setenv("REQUIRE_GO_LIVE_GATE", "false")
    with pytest.raises(ValueError, match="go_live"):
        Settings(
            trading_mode="live",
            binance_api_key="k",
            binance_api_secret="s",
            binance_testnet=False,
            live_confirm="I_UNDERSTAND_REAL_MONEY",
        ).validate()


def test_order_size_cannot_exceed_maximum():
    with pytest.raises(ValueError, match="cannot exceed"):
        Settings(order_size_usdt=100, max_order_size_usdt=50).validate()


def test_entry_min_score_bounds():
    with pytest.raises(ValueError, match="ENTRY_MIN_SCORE"):
        Settings(entry_min_score=0).validate()

def test_live_mode_rejects_unvalidated_multi_position_and_loose_data_age():
    with pytest.raises(ValueError, match="MAX_CONCURRENT_POSITIONS=1"):
        Settings(
            trading_mode="live",
            binance_api_key="k",
            binance_api_secret="s",
            max_concurrent_positions=2,
        ).validate()

    with pytest.raises(ValueError, match="MAX_DATA_AGE_SECONDS"):
        Settings(
            trading_mode="live",
            binance_api_key="k",
            binance_api_secret="s",
            max_data_age_seconds=20,
        ).validate()


def test_legacy_min_edge_env_is_raised_to_safe_floor(monkeypatch):
    from app.config import _min_edge_over_fees

    monkeypatch.setenv("MIN_EDGE_OVER_FEES", "1.5")
    with pytest.warns(RuntimeWarning, match="using 2.0"):
        assert _min_edge_over_fees() == 2.0


def test_min_edge_env_above_safe_floor_is_preserved(monkeypatch):
    from app.config import _min_edge_over_fees

    monkeypatch.setenv("MIN_EDGE_OVER_FEES", "2.5")
    assert _min_edge_over_fees() == 2.5


def test_minimum_order_must_fit_order_cap():
    with pytest.raises(ValueError, match="MIN_ORDER_USDT cannot exceed"):
        Settings(
            order_size_usdt=5,
            min_order_usdt=6,
            max_order_size_usdt=5,
        ).validate()


def test_minimum_order_and_fee_must_fit_starting_cash():
    with pytest.raises(ValueError, match="Minimum order plus quote fee"):
        Settings(starting_cash_usdt=5, min_order_usdt=5, fee_rate=0.001).validate()


def test_20_usdt_live_profile_limits_are_internally_consistent():
    settings = Settings(
        trading_mode="live",
        starting_cash_usdt=20,
        order_size_usdt=5,
        max_order_size_usdt=5,
        min_order_usdt=5,
        max_daily_loss_usdt=1,
        max_daily_fee_usdt=0.15,
        risk_per_trade_pct=0.25,
        max_concurrent_positions=1,
        binance_api_key="test-key",
        binance_api_secret="test-secret",
        binance_testnet=True,
    ).validate()
    assert settings.order_size_usdt <= settings.max_order_size_usdt
    assert settings.max_order_size_usdt <= settings.starting_cash_usdt * 0.25


def test_20_usdt_live_rejects_fee_budget_above_daily_loss():
    with pytest.raises(ValueError, match="MAX_DAILY_FEE_USDT"):
        Settings(
            trading_mode="live",
            starting_cash_usdt=20,
            order_size_usdt=5,
            max_order_size_usdt=5,
            min_order_usdt=5,
            max_daily_loss_usdt=0.10,
            max_daily_fee_usdt=0.15,
            risk_per_trade_pct=0.25,
            binance_api_key="test-key",
            binance_api_secret="test-secret",
            binance_testnet=True,
        ).validate()
