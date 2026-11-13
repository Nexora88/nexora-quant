"""Mainnet live requires explicit LIVE_CONFIRM; testnet remains available."""
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
        "REQUIRE_GO_LIVE_GATE",
        "GO_LIVE_STAMP_PATH",
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
        LIVE_CONFIRM="",
    )
    assert result.returncode != 0
    assert "LIVE_CONFIRM" in result.stderr


def test_mainnet_live_accepted_with_explicit_confirmation() -> None:
    result = _import_config_with(
        TRADING_MODE="live",
        BINANCE_TESTNET="false",
        BINANCE_API_KEY="test-key",
        BINANCE_API_SECRET="test-secret",
        LIVE_CONFIRM="I_UNDERSTAND_REAL_MONEY",
        REQUIRE_GO_LIVE_GATE="false",
    )
    assert result.returncode == 0, result.stderr


def test_mainnet_live_blocked_without_go_live_stamp() -> None:
    result = _import_config_with(
        TRADING_MODE="live",
        BINANCE_TESTNET="false",
        BINANCE_API_KEY="test-key",
        BINANCE_API_SECRET="test-secret",
        LIVE_CONFIRM="I_UNDERSTAND_REAL_MONEY",
        REQUIRE_GO_LIVE_GATE="true",
        GO_LIVE_STAMP_PATH="/tmp/nexora_missing_go_live_stamp",
    )
    assert result.returncode != 0
    assert "GO_LIVE" in result.stderr or "go_live" in result.stderr.lower()


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
