#!/usr/bin/env python3
"""Fail-closed mainnet approval gate.

A fresh paper-session log is necessary but not sufficient. A separate,
operator-reviewed evidence JSON must attest to drawdown, fees, data/ledger
integrity, out-of-sample coverage, Spot Testnet E2E, reconciliation and
kill-switch review. This script never changes TRADING_MODE or places orders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.build_info import source_fingerprint  # noqa: E402

load_dotenv()

MIN_PAPER_HOURS = 168.0
MIN_CLOSED_TRADES = 50
MAX_DRAWDOWN_PCT = 8.0
MAX_DAILY_FEES_USDT = 0.75
MIN_OOS_WINDOWS = 4
MIN_POSITIVE_OOS_WINDOWS = 3


def _number(data: dict, key: str, reasons: list[str]) -> float | None:
    value = data.get(key)
    try:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("not finite")
        return result
    except (TypeError, ValueError):
        reasons.append(f"evidence field {key!r} must be a finite number")
        return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--i-understand-real-money", action="store_true", required=True)
    p.add_argument("--overnight-log", type=Path, required=True)
    p.add_argument("--evidence-json", type=Path, required=True,
                   help="Operator-reviewed scorecard; see docs/GO_LIVE_CHECKLIST.md")
    p.add_argument("--stamp", type=Path, default=ROOT / "data" / "GO_LIVE_OK")
    args = p.parse_args()

    if args.stamp.exists():
        args.stamp.unlink()

    reasons: list[str] = []
    if os.getenv("TRADING_MODE", "paper").strip().lower() != "paper":
        reasons.append("run the go-live gate while TRADING_MODE=paper")

    if not args.overnight_log.is_file():
        reasons.append(f"overnight log not found: {args.overnight_log}")
    else:
        log_text = args.overnight_log.read_text(encoding="utf-8", errors="replace")
        if "OVERNIGHT_CHECK_PASS" not in log_text:
            reasons.append("overnight log missing OVERNIGHT_CHECK_PASS")
        match = re.search(r"INFO checked_at=([^\s]+)", log_text)
        if not match:
            reasons.append("overnight log missing checked_at timestamp")
        else:
            try:
                checked_at = datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
                if checked_at.tzinfo is None:
                    checked_at = checked_at.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - checked_at).total_seconds()
                if age < -300 or age > 15 * 60:
                    reasons.append("overnight check log is stale or from the future; rerun it")
            except ValueError:
                reasons.append("overnight check timestamp is invalid")

    evidence: dict = {}
    if not args.evidence_json.is_file():
        reasons.append(f"operator evidence JSON not found: {args.evidence_json}")
    else:
        try:
            evidence = json.loads(args.evidence_json.read_text(encoding="utf-8"))
            if not isinstance(evidence, dict):
                raise ValueError("top-level JSON value must be an object")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            reasons.append(f"operator evidence JSON unreadable: {exc}")
            evidence = {}

    hours = _number(evidence, "paper_hours", reasons)
    trades = _number(evidence, "closed_trades", reasons)
    expectancy = _number(evidence, "fee_net_expectancy_usdt", reasons)
    drawdown = _number(evidence, "max_drawdown_pct", reasons)
    daily_fees = _number(evidence, "max_daily_fees_usdt", reasons)
    oos_windows = _number(evidence, "oos_windows", reasons)
    positive_oos = _number(evidence, "positive_oos_windows", reasons)
    data_gaps = _number(evidence, "data_gaps", reasons)
    ledger_gaps = _number(evidence, "ledger_gaps", reasons)

    if hours is not None and hours < MIN_PAPER_HOURS:
        reasons.append(f"paper evidence is {hours:.1f}h; need at least {MIN_PAPER_HOURS:.0f}h")
    if trades is not None and trades < MIN_CLOSED_TRADES:
        reasons.append(f"only {trades:.0f} closed trades; need at least {MIN_CLOSED_TRADES}")
    if expectancy is not None and expectancy <= 0:
        reasons.append("fee-net expectancy must be positive")
    if drawdown is not None and not 0 <= drawdown < MAX_DRAWDOWN_PCT:
        reasons.append(f"max drawdown must be below {MAX_DRAWDOWN_PCT:.1f}%")
    if daily_fees is not None and not 0 <= daily_fees <= MAX_DAILY_FEES_USDT:
        reasons.append(f"daily fees must be <= {MAX_DAILY_FEES_USDT:.2f} USDT")
    if oos_windows is not None and oos_windows < MIN_OOS_WINDOWS:
        reasons.append(f"need at least {MIN_OOS_WINDOWS} chronological OOS windows")
    if positive_oos is not None and positive_oos < MIN_POSITIVE_OOS_WINDOWS:
        reasons.append(f"need at least {MIN_POSITIVE_OOS_WINDOWS} positive OOS windows")
    if data_gaps is not None and data_gaps != 0:
        reasons.append("paper evidence contains data gaps")
    if ledger_gaps is not None and ledger_gaps != 0:
        reasons.append("paper evidence contains ledger gaps")

    for key in ("testnet_e2e_pass", "exchange_reconciled", "kill_switch_reviewed"):
        if evidence.get(key) is not True:
            reasons.append(f"operator evidence {key}=true is required")

    if reasons:
        print("GO_LIVE_GATE_FAIL")
        for reason in reasons:
            print(f" - {reason}")
        return 1

    evidence_sha256 = hashlib.sha256(args.evidence_json.read_bytes()).hexdigest()
    args.stamp.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "source_fingerprint": source_fingerprint(ROOT),
        "evidence_sha256": evidence_sha256,
        "evidence_file": str(args.evidence_json),
        "note": "Operator-attested evidence is required; this approval is not a profitability guarantee.",
    }
    args.stamp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("GO_LIVE_GATE_PASS")
    print(f"wrote {args.stamp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
