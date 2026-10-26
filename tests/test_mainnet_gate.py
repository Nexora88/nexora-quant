"""Safety regression tests for the mainnet-disabled execution gate."""
import os
import subprocess
import sys


def _import_config_with(**overrides: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in (
        "TRADING_MODE",
        "BINANCE_TESTNET",
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "LIVE_CONFIRM",
    ):
        env.pop(key, None)
    env.update(overrides)
    return subprocess.run(
        [sys.executable, "-c", "import app.config"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_mainnet_live_is_rejected_without_confirmation() -> None:
    result = _import_config_with(
        TRADING_MODE="live",
        BINANCE_TESTNET="false",
        BINANCE_API_KEY="test-key",
        BINANCE_API_SECRET="test-secret",
    )
    assert result.returncode != 0
    assert "Mainnet live trading is disabled in this build" in result.stderr


def test_mainnet_live_is_rejected_even_with_explicit_confirmation() -> None:
    result = _import_config_with(
        TRADING_MODE="live",
        BINANCE_TESTNET="false",
        BINANCE_API_KEY="test-key",
        BINANCE_API_SECRET="test-secret",
        LIVE_CONFIRM="I_UNDERSTAND_REAL_MONEY",
    )
    assert result.returncode != 0
    assert "Mainnet live trading is disabled in this build" in result.stderr


def test_testnet_live_configuration_remains_available() -> None:
    result = _import_config_with(
        TRADING_MODE="live",
        BINANCE_TESTNET="true",
        BINANCE_API_KEY="test-key",
        BINANCE_API_SECRET="test-secret",
    )
    assert result.returncode == 0, result.stderr


def test_paper_mode_remains_default_without_credentials() -> None:
    result = _import_config_with()
    assert result.returncode == 0, result.stderr
