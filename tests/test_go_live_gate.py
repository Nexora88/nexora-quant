from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.build_info import source_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def run_gate(
    tmp_path: Path, log_text: str, *, mode: str = "paper",
    evidence: dict | None = None,
):
    log_path = tmp_path / "overnight.txt"
    evidence_path = tmp_path / "evidence.json"
    stamp_path = tmp_path / "GO_LIVE_OK"
    if "OVERNIGHT_CHECK_PASS" in log_text and "checked_at" not in log_text:
        log_text = (
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
    result = subprocess.run(
        [
            sys.executable, "scripts/go_live_gate.py",
            "--i-understand-real-money",
            "--overnight-log", str(log_path),
            "--evidence-json", str(evidence_path),
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
    assert payload["evidence_sha256"]


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
