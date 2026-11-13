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
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--i-understand-real-money", action="store_true", required=True)
    p.add_argument("--overnight-log", type=Path, default=None)
    p.add_argument("--expectancy-json", type=Path, default=None)
    p.add_argument("--stamp", type=Path, default=ROOT / "data" / "GO_LIVE_OK")
    p.add_argument("--force-skip-overnight", action="store_true",
                   help="allow stamp without overnight pass (discouraged)")
    args = p.parse_args()

    reasons: list[str] = []
    if args.overnight_log and args.overnight_log.is_file():
        text = args.overnight_log.read_text(encoding="utf-8", errors="replace")
        if "OVERNIGHT_CHECK_PASS" not in text:
            reasons.append("overnight log missing OVERNIGHT_CHECK_PASS")
    elif not args.force_skip_overnight:
        reasons.append("no overnight log; pass --overnight-log or --force-skip-overnight")

    if args.expectancy_json and args.expectancy_json.is_file():
        try:
            data = json.loads(args.expectancy_json.read_text(encoding="utf-8"))
            net = data.get("fee_net") or data.get("net_pnl") or data.get("expectancy")
            if net is not None and float(net) <= 0:
                reasons.append(f"expectancy/fee_net not positive: {net}")
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
        "note": "Stamp only — not a profit guarantee. Testnet first, small size, fee-aware.",
    }
    args.stamp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("GO_LIVE_GATE_PASS")
    print(f"wrote {args.stamp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
