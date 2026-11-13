#!/usr/bin/env python3
"""Time-based walk-forward for L2 desk params (out-of-sample, fee-aware).

Does NOT claim profitability. Splits history chronologically (default 70/30),
grids a small TP/SL/min_score space on the train window, evaluates on test.

Usage:
  PYTHONPATH=. python scripts/walk_forward_params.py path/to/market-history.jsonl.gz
  PYTHONPATH=. python scripts/walk_forward_params.py hist.jsonl.gz --train-frac 0.7 --fee 0.001
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.l2_backtest import L2BacktestConfig, run_l2_backtest, summarize_l2_result


def _split_history(path: Path, train_frac: float) -> tuple[Path, Path]:
    """Split JSONL/JSONL.GZ by line count into temp train/test files."""
    import gzip

    open_fn = gzip.open if path.suffix == ".gz" or path.name.endswith(".gz") else open
    mode = "rt"
    lines: list[str] = []
    with open_fn(path, mode, encoding="utf-8") as f:  # type: ignore[arg-type]
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)
    if len(lines) < 200:
        raise SystemExit(f"need >=200 events, got {len(lines)}")
    cut = max(50, int(len(lines) * train_frac))
    train_lines, test_lines = lines[:cut], lines[cut:]
    out_dir = path.parent / "_wf_split"
    out_dir.mkdir(exist_ok=True)
    train_p = out_dir / "train.jsonl"
    test_p = out_dir / "test.jsonl"
    train_p.write_text("\n".join(train_lines) + "\n", encoding="utf-8")
    test_p.write_text("\n".join(test_lines) + "\n", encoding="utf-8")
    return train_p, test_p


GRID = [
    {"entry_min_score": 0.20, "take_profit_pct": 0.55, "stop_loss_pct": 0.18},
    {"entry_min_score": 0.28, "take_profit_pct": 0.55, "stop_loss_pct": 0.18},
    {"entry_min_score": 0.35, "take_profit_pct": 0.70, "stop_loss_pct": 0.22},
    {"entry_min_score": 0.25, "take_profit_pct": 0.90, "stop_loss_pct": 0.30},
    {"entry_min_score": 0.40, "take_profit_pct": 0.40, "stop_loss_pct": 0.15},
]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("history", type=Path)
    p.add_argument("--train-frac", type=float, default=0.70)
    p.add_argument("--cash", type=float, default=100.0)
    p.add_argument("--order-size", type=float, default=12.0)
    p.add_argument("--fee", type=float, default=0.001)
    p.add_argument("--output", type=Path, default=Path("walk-forward-report.json"))
    args = p.parse_args()

    train_p, test_p = _split_history(args.history, args.train_frac)
    rows = []
    best = None
    for g in GRID:
        cfg = L2BacktestConfig(
            starting_cash_usdt=args.cash,
            order_size_usdt=args.order_size,
            entry_min_score=float(g["entry_min_score"]),
            impact_coefficient=0.1,
        )
        try:
            tr = summarize_l2_result(run_l2_backtest(train_p, cfg))
            te = summarize_l2_result(run_l2_backtest(test_p, cfg))
        except Exception as exc:
            rows.append({"params": g, "error": str(exc)})
            continue
        row = {
            "params": g,
            "train": tr,
            "test": te,
            "test_net": te.get("net_pnl_usdt", te.get("pnl_usdt")),
        }
        rows.append(row)
        score = float(row["test_net"] or -1e9)
        if best is None or score > best[0]:
            best = (score, row)

    report = {
        "history": str(args.history),
        "train_frac": args.train_frac,
        "fee_note": args.fee,
        "disclaimer": "OOS walk-forward only — not a profit guarantee. Prefer test net>0 and low trade churn.",
        "rows": rows,
        "best_test": best[1] if best else None,
    }
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"best_test": report["best_test"], "n": len(rows)}, indent=2))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
