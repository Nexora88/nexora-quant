from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.build_info import source_fingerprint
from app.live_approval import read_mainnet_approval
from app.live_execution_evidence import SpotEvidenceScope

ROOT = Path(__file__).resolve().parents[1]


def run_gate(
    tmp_path: Path, log_text: str, *, mode: str = "paper",
    evidence: dict | None = None,
    overlap: bool = False, testnet_skipped: bool = False,
):
    log_path = tmp_path / "overnight.txt"
    evidence_path = tmp_path / "evidence.json"
    stamp_path = tmp_path / "GO_LIVE_OK"
    profile_path = tmp_path / "profile.json"
    oos_path = tmp_path / "out-of-sample.json"
    testnet_path = tmp_path / "signed-testnet.xml"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text("#!/bin/sh\\nexit 0\\n", encoding="utf-8")
    fake_gh.chmod(0o755)
    capture_path = tmp_path / "btcusdt.jsonl"
    manifest_path = tmp_path / "manifest.json"
    capture_path.write_text("{}\\n", encoding="utf-8")
    capture_digest = __import__("hashlib").sha256(capture_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps({
        "schema_version": 1, "source": "binance_spot_public", "research_only": True,
        "coverage_ok": True,
        "captures": [{"file": capture_path.name, "coverage_ok": True,
                      "symbol": "BTCUSDT", "sha256": capture_digest}],
    }), encoding="utf-8")
    if "OVERNIGHT_CHECK_PASS" in log_text and "checked_at" not in log_text:
        log_text = (
            "INFO session=mock duration=168.10h ticks=2000 reconnects=0 stale=0.0m\n"
            "INFO closed_trades=50 fee_net_total=0.500000 fee_net_expectancy=0.010000 USDT/trade\n"
            f"INFO checked_at={datetime.now(timezone.utc).isoformat()}\n" + log_text
        )
    log_path.write_text(log_text, encoding="utf-8")
    scorecard = evidence or {
        "paper_hours": 168,
        "closed_trades": 50,
        "fee_net_expectancy_usdt": 0.01,
        "max_drawdown_pct": 4.0,
        "max_daily_fees_usdt": 0.5,
        "data_gaps": 0,
        "ledger_gaps": 0,
        "oos_windows": 4,
        "positive_oos_windows": 3,
        "testnet_e2e_pass": True,
        "exchange_reconciled": True,
        "kill_switch_reviewed": True,
    }
    evidence_path.write_text(json.dumps(scorecard), encoding="utf-8")
    env = os.environ.copy()
    env["TRADING_MODE"] = mode
    env["PYTHONPATH"] = str(ROOT)
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    env["PYTHON_DOTENV_DISABLED"] = "true"
    profile_path.write_text(subprocess.check_output(
        [sys.executable, "-m", "app.config", "--describe-mainnet-profile"],
        cwd=ROOT, env={**env, "TRADING_MODE": "live", "BINANCE_TESTNET": "false", "SYMBOL": "btcusdt"}, text=True,
    ), encoding="utf-8")
    profile = json.loads(profile_path.read_text())
    windows = []
    for i in range(4):
        first = 100_000_000_000 * (i + 1)
        windows.append({
            "window": i + 1, "train_last_timestamp_ns": first - 61_000_000_000,
            "test_first_timestamp_ns": first, "test_last_timestamp_ns": first + 5_000_000_000,
            "no_trade_fallback": False,
            "unseen_test_metrics": {
                "return_pct": 0.5 if i < 3 else -1.0,
                "realized_pnl": 0.5 if i < 3 else -1.0,
                "closed_position_count": 5, "final_open_quantity": 0,
                "pending_orders_at_end": 0, "invalid_depth_frames": 0, "max_drawdown_pct": 3.4,
            },
        })
    if overlap:
        windows[0]["test_last_timestamp_ns"] = windows[1]["test_first_timestamp_ns"]
    oos_path.write_text(json.dumps({
        "mode": "rolling_walk_forward_research_only", "embargo_seconds": 60,
        "selection_policy": "train_only_with_time_embargo_then_single_unseen_test_per_window",
        "source_fingerprint": source_fingerprint(ROOT), "windows_requested": 4,
        "starting_cash_per_asset_usdt": profile["starting_cash_usdt"],
        "order_size_usdt": profile["order_size_usdt"], "fee_rate": profile["effective_fee_rate"],
        "assets": {"btcusdt": {
            "windows": windows, "verified_capture_sha256": capture_digest,
            "source": str(capture_path.resolve()),
            "verified_capture_manifest": str(manifest_path.resolve()),
        }},
    }), encoding="utf-8")
    testnet_path.write_text(
        f'<testsuite tests="1" skipped="{int(testnet_skipped)}">'
        '<testcase classname="tests.test_spot_testnet_e2e" name="test_spot_testnet_market_oco_restart_cancel_and_exit">'
        + ("<skipped/>" if testnet_skipped else "") + "</testcase></testsuite>", encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable, "scripts/go_live_gate.py",
            "--i-understand-real-money",
            "--overnight-log", str(log_path),
            "--evidence-json", str(evidence_path),
            "--live-profile", str(profile_path),
            "--mainnet-account-uid", "77",
            "--oos-report", str(oos_path),
            "--testnet-junit", str(testnet_path),
            "--testnet-source-sha", "a" * 40,
            "--stamp", str(stamp_path),
        ],
        cwd=ROOT, env=env, capture_output=True, text=True, check=False,
    )
    return result, stamp_path


def test_gate_creates_source_bound_stamp_only_after_full_evidence_pass(tmp_path):
    result, stamp = run_gate(tmp_path, "OVERNIGHT_CHECK_PASS\n")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(stamp.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["source_fingerprint"] == source_fingerprint(ROOT)
    assert payload["artifacts"]["scorecard"]["sha256"]
    assert payload["testnet_source_sha"] == "a" * 40
    profile = json.loads((tmp_path / "profile.json").read_text())
    assert read_mainnet_approval(stamp, root=ROOT, profile=profile) == SpotEvidenceScope(77, False, "BTCUSDT").stamp()[
        "account_binding"
    ]


def test_gate_rejects_failed_paper_log_and_non_paper_mode(tmp_path):
    failed, stamp = run_gate(tmp_path, "OVERNIGHT_CHECK_FAIL\n")
    assert failed.returncode != 0
    assert not stamp.exists()

    live, _ = run_gate(tmp_path, "OVERNIGHT_CHECK_PASS\n", mode="live")
    assert live.returncode != 0
    assert "TRADING_MODE=paper" in live.stdout


def test_gate_rejects_incomplete_scorecard_and_removes_old_stamp(tmp_path):
    evidence = {
        "paper_hours": 24,
        "closed_trades": 2,
        "fee_net_expectancy_usdt": -0.1,
        "max_drawdown_pct": 12,
        "max_daily_fees_usdt": 2,
        "data_gaps": 1,
        "ledger_gaps": 1,
        "oos_windows": 1,
        "positive_oos_windows": 0,
        "testnet_e2e_pass": False,
        "exchange_reconciled": False,
        "kill_switch_reviewed": False,
    }
    result, stamp = run_gate(
        tmp_path, "OVERNIGHT_CHECK_PASS\n", evidence=evidence,
    )
    assert result.returncode != 0
    assert "GO_LIVE_GATE_FAIL" in result.stdout
    assert not stamp.exists()


@pytest.mark.parametrize(("options", "error"), [
    ({"overlap": True}, "windows overlap"),
    ({"testnet_skipped": True}, "lifecycle did not pass"),
])
def test_gate_rejects_invalid_machine_artifacts(tmp_path, options, error):
    stamp = tmp_path / "GO_LIVE_OK"
    stamp.write_text("old approval")
    result, stamp = run_gate(tmp_path, "OVERNIGHT_CHECK_PASS\n", **options)
    assert result.returncode == 1
    assert error in result.stdout
    assert not stamp.exists()


def test_gate_does_not_accept_a_partial_pass_marker(tmp_path):
    result, stamp = run_gate(tmp_path, "NOT_OVERNIGHT_CHECK_PASS\n")
    assert result.returncode == 1
    assert "missing OVERNIGHT_CHECK_PASS" in result.stdout
    assert not stamp.exists()
