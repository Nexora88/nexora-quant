import os
import pytest
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


def test_mainnet_live_requires_explicit_confirm():
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


def test_mainnet_live_accepted_with_confirm():
    s = Settings(
        trading_mode="live",
        binance_api_key="k",
        binance_api_secret="s",
        binance_testnet=False,
        live_confirm="I_UNDERSTAND_REAL_MONEY",
    ).validate()
    assert s.trading_mode == "live"
    assert s.binance_testnet is False


def test_order_size_cannot_exceed_maximum():
    with pytest.raises(ValueError, match="cannot exceed"):
        Settings(order_size_usdt=100, max_order_size_usdt=50).validate()


def test_entry_min_score_bounds():
    with pytest.raises(ValueError, match="ENTRY_MIN_SCORE"):
        Settings(entry_min_score=0).validate()
