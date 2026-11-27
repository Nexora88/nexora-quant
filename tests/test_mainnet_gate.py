"""Mainnet live requires explicit LIVE_CONFIRM; testnet remains available."""
import json
import os
import subprocess
import sys
from pathlib import Path

from tests._approval_fixtures import write_approval_stamp


def _approval_stamp(path: Path) -> None:
    env = {**os.environ, "TRADING_MODE": "live", "BINANCE_TESTNET": "false", "PYTHON_DOTENV_DISABLED": "true"}
    env.pop("LIVE_DB_PATH", None)
    profile = subprocess.check_output(
        [sys.executable, "-m", "app.config", "--describe-mainnet-profile"],
        env=env, text=True,
    )
    assert not ({"binance_api_key", "binance_api_secret", "jwt_secret"} & json.loads(profile).keys())
    write_approval_stamp(path, json.loads(profile))


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
        "LIVE_DB_PATH",
    ):
        env.pop(key, None)
    env.update(overrides)
    env["PYTHON_DOTENV_DISABLED"] = "true"
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


def test_mainnet_live_requires_confirmation_and_validated_stamp(tmp_path) -> None:
    stamp = tmp_path / "GO_LIVE_OK"
    _approval_stamp(stamp)
    result = _import_config_with(
        TRADING_MODE="live",
        BINANCE_TESTNET="false",
        BINANCE_API_KEY="test-key",
        BINANCE_API_SECRET="test-secret",
        LIVE_CONFIRM="I_UNDERSTAND_REAL_MONEY",
        GO_LIVE_STAMP_PATH=str(stamp),
    )
    assert result.returncode == 0, result.stderr


def test_mainnet_live_cannot_reuse_approval_after_risk_or_artifact_change(tmp_path) -> None:
    stamp = tmp_path / "GO_LIVE_OK"
    _approval_stamp(stamp)
    env = {
        "TRADING_MODE": "live", "BINANCE_TESTNET": "false", "BINANCE_API_KEY": "test-key",
        "BINANCE_API_SECRET": "test-secret", "LIVE_CONFIRM": "I_UNDERSTAND_REAL_MONEY",
        "GO_LIVE_STAMP_PATH": str(stamp),
    }
    result = _import_config_with(**env, MAX_DAILY_LOSS_USDT="1.25")
    assert result.returncode != 0
    assert "settings changed" in result.stderr
    (tmp_path / "fixture-testnet").write_text("modified!", encoding="utf-8")
    result = _import_config_with(**env)
    assert result.returncode != 0
    assert "testnet artifact changed" in result.stderr


def test_mainnet_gate_cannot_be_disabled_with_environment_override() -> None:
    result = _import_config_with(
        TRADING_MODE="live",
        BINANCE_TESTNET="false",
        BINANCE_API_KEY="test-key",
        BINANCE_API_SECRET="test-secret",
        LIVE_CONFIRM="I_UNDERSTAND_REAL_MONEY",
        REQUIRE_GO_LIVE_GATE="false",
        GO_LIVE_STAMP_PATH="/tmp/nexora_missing_go_live_stamp",
    )
    assert result.returncode != 0
    assert "GO_LIVE" in result.stderr or "go_live" in result.stderr.lower()


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



def test_testnet_and_mainnet_live_ledgers_are_isolated(tmp_path) -> None:
    stamp = tmp_path / "GO_LIVE_OK"
    _approval_stamp(stamp)
    for testnet, expected in (
        ("true", "data/live-testnet.sqlite3"),
        ("false", "data/live.sqlite3"),
    ):
        env = os.environ.copy()
        for key in ("TRADING_MODE", "BINANCE_TESTNET", "BINANCE_API_KEY",
                    "BINANCE_API_SECRET", "LIVE_DB_PATH"):
            env.pop(key, None)
        env.update({
            "TRADING_MODE": "live",
            "BINANCE_TESTNET": testnet,
            "BINANCE_API_KEY": "test-key",
            "BINANCE_API_SECRET": "test-secret",
            "LIVE_CONFIRM": "I_UNDERSTAND_REAL_MONEY",
            "GO_LIVE_STAMP_PATH": str(stamp),
        })
        result = subprocess.run(
            [sys.executable, "-c",
             "from app.config import settings; print(settings.store_path)"],
            env=env, capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected
