#!/usr/bin/env python3
"""Replay L2 JSONL.gz through the event-driven backtest engine."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.l2_backtest import L2BacktestConfig, run_l2_backtest, summarize_l2_result


def main() -> None:
    p = argparse.ArgumentParser(description="L2 event-driven backtest")
    p.add_argument("history", type=Path, help="path to market-history.jsonl.gz")
    p.add_argument("--cash", type=float, default=1000.0)
    p.add_argument("--order-size", type=float, default=25.0)
    p.add_argument("--min-score", type=float, default=0.55)
    p.add_argument("--impact", type=float, default=0.1)
    args = p.parse_args()
    cfg = L2BacktestConfig(
        starting_cash_usdt=args.cash,
        order_size_usdt=args.order_size,
        entry_min_score=args.min_score,
        impact_coefficient=args.impact,
    )
    result = run_l2_backtest(args.history, cfg)
    print(json.dumps(summarize_l2_result(result), indent=2))


if __name__ == "__main__":
    main()
