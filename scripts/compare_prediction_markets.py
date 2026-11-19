#!/usr/bin/env python3
"""Compare saved OpticOdds and Polymarket NBA moneyline snapshots. No network or trades."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.market_comparison import ComparisonPolicy, compare_moneyline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", help="JSON match manifest and provider snapshots; use - for stdin")
    parser.add_argument("--as-of", help="ISO-8601 timestamp with timezone; default: current UTC")
    parser.add_argument("--shares", type=float, default=10)
    parser.add_argument("--min-books", type=int, default=2)
    parser.add_argument("--max-age-seconds", type=float, default=120)
    parser.add_argument("--max-skew-seconds", type=float, default=60)
    parser.add_argument("--max-spread", type=float, default=0.10)
    parser.add_argument("--cost-bps", type=float, help="optional assumed cost on ask notional")
    args = parser.parse_args()
    try:
        as_of = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC)
        policy = ComparisonPolicy(
            shares=args.shares, min_books=args.min_books, max_age_seconds=args.max_age_seconds,
            max_skew_seconds=args.max_skew_seconds, max_spread=args.max_spread, cost_bps=args.cost_bps,
        )
        bundle = (
            json.load(sys.stdin) if args.bundle == "-"
            else json.loads(Path(args.bundle).read_text(encoding="utf-8"))
        )
        if not isinstance(bundle, dict):
            raise ValueError("bundle must be a JSON object")
        report = compare_moneyline(bundle, as_of=as_of, policy=policy)
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    except (OSError, ValueError) as exc:
        print(f"MARKET_COMPARISON_ERROR: {exc}", file=sys.stderr)
        return 1
    return 0 if report["status"] == "comparable" else 2


if __name__ == "__main__":
    raise SystemExit(main())
