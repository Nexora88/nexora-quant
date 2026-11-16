"""Mainnet live requires explicit LIVE_CONFIRM; testnet remains available."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.build_info import source_fingerprint


def _approval_stamp(path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    path.write_text(json.dumps({
        "ok": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "source_fingerprint": source_fingerprint(root),
    }), encoding="utf-8")


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
