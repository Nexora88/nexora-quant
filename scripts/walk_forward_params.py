#!/usr/bin/env python3
"""Chronological walk-forward for L2 desk parameters.

Candidates are ranked only on the training segment. Exactly one selected
configuration is evaluated on the later unseen test segment; test performance
is never used to select or re-rank candidates.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.l2_backtest import L2BacktestConfig, run_l2_backtest, summarize_l2_result
from app.history_windows import DEFAULT_EMBARGO_SECONDS, embargo_nanoseconds, event_timestamps, purged_bounds


GRID = [
    {"entry_min_score": 0.20, "take_profit_pct": 0.55, "stop_loss_pct": 0.18},
    {"entry_min_score": 0.28, "take_profit_pct": 0.55, "stop_loss_pct": 0.18},
    {"entry_min_score": 0.35, "take_profit_pct": 0.70, "stop_loss_pct": 0.22},
    {"entry_min_score": 0.25, "take_profit_pct": 0.90, "stop_loss_pct": 0.30},
    {"entry_min_score": 0.40, "take_profit_pct": 0.40, "stop_loss_pct": 0.15},
]


def _split_history(
    path: Path, train_frac: float, *, embargo_seconds: float = DEFAULT_EMBARGO_SECONDS,
) -> tuple[Path, Path]:
    """Split chronologically, with a time embargo and no shared timestamps."""
    if not 0.5 <= train_frac < 1.0:
        raise ValueError("train_frac must be in [0.5, 1.0)")
    open_fn = gzip.open if path.suffix == ".gz" or path.name.endswith(".gz") else open
    lines: list[str] = []
    with open_fn(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if line:
                lines.append(line)
    if len(lines) < 200:
        raise ValueError(f"need >=200 events, got {len(lines)}")
    cut = int(len(lines) * train_frac)
    train_end, test_start, test_end = purged_bounds(
        event_timestamps(lines), cut, len(lines), embargo_nanoseconds(embargo_seconds),
    )
    out_dir = path.parent / "_wf_split"
    out_dir.mkdir(exist_ok=True)
    train_path = out_dir / "train.jsonl"
    test_path = out_dir / "test.jsonl"
    train_path.write_text("\n".join(lines[:train_end]) + "\n", encoding="utf-8")
    test_path.write_text("\n".join(lines[test_start:test_end]) + "\n", encoding="utf-8")
    return train_path, test_path


def evaluate_train_then_test(
    train_path: Path,
    test_path: Path,
    *,
    candidates: list[dict[str, float]] | None = None,
    fee_rate: float = 0.001,
    cash: float = 100.0,
    order_size: float = 12.0,
) -> dict[str, Any]:
    """Select using train metrics, then evaluate only the winner out of sample."""
    choices = candidates or GRID
    if not choices:
        raise ValueError("at least one candidate is required")
    if not 0 <= fee_rate < 0.1 or not math.isfinite(cash) or cash <= 0:
        raise ValueError("fee_rate must be in [0, 0.1) and cash must be finite and positive")

    training: list[dict[str, Any]] = []
    for candidate in choices:
        config = L2BacktestConfig(
            starting_cash_usdt=cash,
            order_size_usdt=order_size,
            fee_rate=fee_rate,
            entry_min_score=float(candidate["entry_min_score"]),
            take_profit_pct=float(candidate.get("take_profit_pct", 0.55)),
            stop_loss_pct=float(candidate.get("stop_loss_pct", 0.18)),
            impact_coefficient=0.1,
        )
        metrics = summarize_l2_result(run_l2_backtest(train_path, config))
        training.append({"params": dict(candidate), "metrics": metrics})

    # An open marked position is not a proven exit. Require at least one actual
    # round trip and rank on fee-net realized PnL with a marked drawdown penalty.
    for row in training:
        metrics = row["metrics"]
        metrics["selection_score"] = (
            (float(metrics["realized_pnl"]) / cash) * 100
            - 0.5 * float(metrics.get("max_drawdown_pct") or 0.0)
        ) if int(metrics.get("closed_position_count") or 0) > 0 else None
    eligible = [row for row in training if row["metrics"]["selection_score"] is not None]
    winner = max(eligible, key=lambda row: row["metrics"]["selection_score"], default=None)
    no_trade_fallback = winner is None or winner["metrics"]["selection_score"] <= 0
    selected = (
        {"entry_min_score": 1.01, "take_profit_pct": 0.55, "stop_loss_pct": 0.18}
        if no_trade_fallback else winner["params"]
    )
    selected_training_metrics = (
        {"return_pct": 0.0, "max_drawdown_pct": 0.0, "selection_score": 0.0,
         "policy": "no_trade_fallback"}
        if no_trade_fallback else winner["metrics"]
    )
    test_config = L2BacktestConfig(
        starting_cash_usdt=cash,
        order_size_usdt=order_size,
        fee_rate=fee_rate,
        entry_min_score=float(selected["entry_min_score"]),
        take_profit_pct=float(selected.get("take_profit_pct", 0.55)),
        stop_loss_pct=float(selected.get("stop_loss_pct", 0.18)),
        impact_coefficient=0.1,
    )
    test_metrics = summarize_l2_result(run_l2_backtest(test_path, test_config))
    return {
        "selected_params": selected,
        "selected_training_metrics": selected_training_metrics,
        "unseen_test_metrics": test_metrics,
        "no_trade_fallback": no_trade_fallback,
        "candidate_training_metrics": training,
        "fee_rate": fee_rate,
        "warning": (
            "Only realized training PnL and drawdown selected parameters. The later test segment was run "
            "once for the winner. One split is not proof of robustness; repeat rolling "
            "windows across multiple assets and market regimes."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("history", type=Path)
    parser.add_argument("--train-frac", type=float, default=0.70)
    parser.add_argument("--cash", type=float, default=100.0)
    parser.add_argument("--order-size", type=float, default=12.0)
    parser.add_argument("--fee", type=float, default=0.001)
    parser.add_argument("--embargo-seconds", type=float, default=DEFAULT_EMBARGO_SECONDS)
    parser.add_argument("--output", type=Path, default=Path("walk-forward-report.json"))
    args = parser.parse_args()

    if args.cash <= 0 or args.order_size <= 0:
        parser.error("--cash and --order-size must be positive")
    try:
        train_path, test_path = _split_history(args.history, args.train_frac, embargo_seconds=args.embargo_seconds)
        report = evaluate_train_then_test(
            train_path, test_path, fee_rate=args.fee,
            cash=args.cash, order_size=args.order_size,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"WALK_FORWARD_FAIL: {exc}")
        return 1

    report.update({
        "history": str(args.history),
        "train_frac": args.train_frac,
        "embargo_seconds": args.embargo_seconds,
        "train_events_file": str(train_path),
        "test_events_file": str(test_path),
    })
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "selected_params": report["selected_params"],
        "train": report["selected_training_metrics"],
        "unseen_test": report["unseen_test_metrics"],
    }, indent=2))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
