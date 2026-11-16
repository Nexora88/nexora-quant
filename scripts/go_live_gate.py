#!/usr/bin/env python3
"""Hard gate before mainnet live: write data/GO_LIVE_OK only if checks pass.

Checks (minimal, honest):
  1. TRADING_MODE must still be paper while evaluating (we do not flip mode here)
  2. Optional overnight report path contains OVERNIGHT_CHECK_PASS
  3. User must pass --i-understand-real-money
  4. Optional expectancy JSON with fee_net > 0

Usage:
  PYTHONPATH=. python scripts/go_live_gate.py --i-understand-real-money \\
      --overnight-log path/to/overnight.txt \\
      --expectancy-json path/to/expectancy.json
"""
from __future__ import annotations

import argparse
import json
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


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--i-understand-real-money", action="store_true", required=True)
    p.add_argument("--overnight-log", type=Path, required=True)
    p.add_argument("--expectancy-json", type=Path, default=None)
    p.add_argument("--stamp", type=Path, default=ROOT / "data" / "GO_LIVE_OK")
    args = p.parse_args()

    # A failed re-check must never leave a previously valid approval in place.
    if args.stamp.exists():
        args.stamp.unlink()

    reasons: list[str] = []
    if os.getenv("TRADING_MODE", "paper").strip().lower() != "paper":
        reasons.append("run the go-live gate while TRADING_MODE=paper")
    if not args.overnight_log.is_file():
        reasons.append(f"overnight log not found: {args.overnight_log}")
    else:
        text = args.overnight_log.read_text(encoding="utf-8", errors="replace")
        if "OVERNIGHT_CHECK_PASS" not in text:
            reasons.append("overnight log missing OVERNIGHT_CHECK_PASS")
        checked_match = re.search(r"INFO checked_at=([^\s]+)", text)
        if not checked_match:
            reasons.append("overnight log missing a fresh checked_at timestamp")
        else:
            try:
                checked_at = datetime.fromisoformat(checked_match.group(1).replace("Z", "+00:00"))
                if checked_at.tzinfo is None:
                    checked_at = checked_at.replace(tzinfo=timezone.utc)
                age_seconds = (datetime.now(timezone.utc) - checked_at).total_seconds()
                if age_seconds < -300 or age_seconds > 15 * 60:
                    reasons.append("overnight check log is stale or from the future; rerun it")
            except ValueError:
                reasons.append("overnight check timestamp is invalid")

    if args.expectancy_json:
        if not args.expectancy_json.is_file():
            reasons.append(f"expectancy json not found: {args.expectancy_json}")
        else:
            try:
                data = json.loads(args.expectancy_json.read_text(encoding="utf-8"))
                net = next(
                    (data[key] for key in ("fee_net", "net_pnl", "expectancy") if key in data),
                    None,
                )
                if net is None or float(net) <= 0:
                    reasons.append(f"expectancy/fee_net not positive or missing: {net}")
            except Exception as exc:
                reasons.append(f"expectancy json unreadable: {exc}")

    if reasons:
        print("GO_LIVE_GATE_FAIL")
        for r in reasons:
            print(f" - {r}")
        return 1

    args.stamp.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "source_fingerprint": source_fingerprint(ROOT),
        "note": "Approval is bound to this exact source tree; any runtime source change invalidates it.",
    }
    args.stamp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("GO_LIVE_GATE_PASS")
    print(f"wrote {args.stamp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
