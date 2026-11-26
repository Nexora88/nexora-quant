#!/usr/bin/env python3
"""Expanding-window, multi-asset L2 walk-forward diagnostics.

Each window selects parameters on its chronological training prefix only, then
runs the selected policy once on the immediately following unseen segment.
This is research-only; no exchange orders are created.
"""
from __future__ import annotations

import argparse
import gzip
import json
import tempfile
import sys
from pathlib import Path
from statistics import median
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.build_info import source_fingerprint
from app.history_windows import DEFAULT_EMBARGO_SECONDS, embargo_nanoseconds, event_timestamps, purged_bounds
from app.market_history import verify_capture_archive
from scripts.walk_forward_params import evaluate_train_then_test


def _read_events(path: Path) -> tuple[list[str], list[int]]:
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as stream:
        rows = [line.strip() for line in stream if line.strip()]
    if len(rows) < 500:
        raise ValueError(f"{path}: need at least 500 events, got {len(rows)}")
    try:
        return rows, event_timestamps(rows)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def rolling_bounds(event_count: int, windows: int) -> list[tuple[int, int, int]]:
    """Return expanding train end and non-overlapping next test bounds."""
    if windows < 1 or event_count < 500:
        raise ValueError("windows must be >=1 and event_count must be >=500")
    test_width = event_count // (windows + 5)
    first_train = event_count - windows * test_width
    if first_train < 200 or test_width < 50:
        raise ValueError("history is too short for requested rolling windows")
    result = []
    for index in range(windows):
        train_end = first_train + index * test_width
        test_end = train_end + test_width
        result.append((train_end, train_end, test_end))
    return result


def run_rolling_walk_forward(
    histories: dict[str, Path],
    *,
    windows: int = 2,
    cash: float = 100.0,
    order_size: float = 12.0,
    fee_rate: float = 0.001,
    embargo_seconds: float = DEFAULT_EMBARGO_SECONDS,
    capture_manifests: dict[str, Path] | None = None,
) -> dict[str, Any]:
    if not histories:
        raise ValueError("at least one asset history is required")
    if any(not symbol.isascii() or not symbol.isalnum() for symbol in histories):
        raise ValueError("history labels must be alphanumeric ASCII identifiers")
    if capture_manifests is not None and set(capture_manifests) != set(histories):
        raise ValueError("A capture manifest is required for every reported history")
    embargo_ns = embargo_nanoseconds(embargo_seconds)
    report: dict[str, Any] = {
        "mode": "rolling_walk_forward_research_only",
        "selection_policy": "train_only_with_time_embargo_then_single_unseen_test_per_window",
        "embargo_seconds": embargo_seconds,
        "windows_requested": windows,
        "fee_rate": fee_rate,
        "starting_cash_per_asset_usdt": cash,
        "order_size_usdt": order_size,
        "source_fingerprint": source_fingerprint(Path(__file__).resolve().parents[1]),
        "assets": {},
    }
    with tempfile.TemporaryDirectory(prefix="nexora-rolling-wf-") as tmp:
        temp = Path(tmp)
        for symbol, source in sorted(histories.items()):
            digest = (
                verify_capture_archive(source, capture_manifests[symbol], symbol=symbol)
                if capture_manifests is not None else None
            )
            rows, timestamps = _read_events(source)
            asset_windows = []
            for number, (_, proposed_start, proposed_end) in enumerate(
                rolling_bounds(len(rows), windows), start=1
            ):
                train_end, test_start, test_end = purged_bounds(
                    timestamps, proposed_start, proposed_end, embargo_ns,
                )
                train_path = temp / f"{symbol}-{number}-train.jsonl"
                test_path = temp / f"{symbol}-{number}-test.jsonl"
                train_path.write_text("\n".join(rows[:train_end]) + "\n", encoding="utf-8")
                test_path.write_text("\n".join(rows[test_start:test_end]) + "\n", encoding="utf-8")
                result = evaluate_train_then_test(
                    train_path, test_path, fee_rate=fee_rate,
                    cash=cash, order_size=order_size,
                )
                unseen = result["unseen_test_metrics"]
                asset_windows.append({
                    "window": number,
                    "train_events": train_end,
                    "test_events": test_end - test_start,
                    "train_end_event_index": train_end - 1,
                    "test_start_event_index": test_start,
                    "test_end_event_index_exclusive": test_end,
                    "omitted_events": test_start - train_end,
                    "train_last_timestamp_ns": timestamps[train_end - 1],
                    "test_first_timestamp_ns": timestamps[test_start],
                    "test_last_timestamp_ns": timestamps[test_end - 1],
                    "no_trade_fallback": result["no_trade_fallback"],
                    "selected_params": result["selected_params"],
                    "selected_training_metrics": {
                        key: result["selected_training_metrics"].get(key)
                        for key in (
                            "return_pct", "realized_pnl", "closed_position_count",
                            "max_drawdown_pct", "selection_score", "policy",
                        )
                    },
                    "unseen_test_metrics": {
                        key: unseen.get(key) for key in (
                            "entries", "exits", "closed_position_count",
                            "expectancy_usdt_per_exit_fill", "profit_factor_per_exit_fill",
                            "fees_paid_usdt", "max_drawdown_pct", "final_equity",
                            "return_pct", "realized_pnl", "final_open_quantity",
                            "unfilled_orders", "pending_orders_at_end", "invalid_depth_frames",
                            "ending_valuation",
                        )
                    },
                })
            returns = [w["unseen_test_metrics"]["return_pct"] for w in asset_windows]
            report["assets"][symbol] = {
                "source": str(source.resolve()),
                "verified_capture_sha256": digest,
                "verified_capture_manifest": (
                    str(capture_manifests[symbol].resolve()) if capture_manifests is not None else None
                ),
                "events": len(rows),
                "windows": asset_windows,
                "window_return_median_pct": median(returns) if returns else None,
                "window_return_worst_pct": min(returns) if returns else None,
                "positive_windows": sum(value > 0 for value in returns),
                "positive_flat_windows": sum(
                    w["unseen_test_metrics"]["return_pct"] > 0
                    and (w["unseen_test_metrics"]["closed_position_count"] or 0) > 0
                    and w["unseen_test_metrics"]["final_open_quantity"] == 0
                    and w["unseen_test_metrics"]["pending_orders_at_end"] == 0
                    for w in asset_windows
                ),
            }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("histories", nargs="+", type=Path, help="market-history*.jsonl[.gz] files")
    parser.add_argument("--windows", type=int, default=2)
    parser.add_argument("--cash", type=float, default=100.0)
    parser.add_argument("--order-size", type=float, default=12.0)
    parser.add_argument("--fee", type=float, default=0.001)
    parser.add_argument("--embargo-seconds", type=float, default=DEFAULT_EMBARGO_SECONDS)
    parser.add_argument("--output", type=Path, default=Path("rolling-walk-forward.json"))
    parser.add_argument(
        "--require-capture-manifests", action="store_true",
        help="verify each archive against its sibling manifest.json before evaluating it",
    )
    args = parser.parse_args()
    if args.cash <= 0 or args.order_size <= 0 or not 0 <= args.fee < 0.1:
        parser.error("cash/order-size must be positive and fee must be in [0, 0.1)")
    histories = {}
    for path in args.histories:
        name = path.name.removesuffix(".gz").removesuffix(".jsonl")
        label = (name.removeprefix("market-history-").removeprefix("market-history") or "primary").lower()
        if label in histories:
            parser.error(f"duplicate history label {label!r}")
        histories[label] = path
    try:
        report = run_rolling_walk_forward(
            histories, windows=args.windows, cash=args.cash,
            order_size=args.order_size, fee_rate=args.fee, embargo_seconds=args.embargo_seconds,
            capture_manifests=(
                {symbol: path.with_name("manifest.json") for symbol, path in histories.items()}
                if args.require_capture_manifests else None
            ),
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"ROLLING_WALK_FORWARD_FAIL: {exc}")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        symbol: {
            "events": value["events"],
            "window_return_worst_pct": value["window_return_worst_pct"],
            "window_return_median_pct": value["window_return_median_pct"],
            "positive_windows": value["positive_windows"],
            "positive_flat_windows": value["positive_flat_windows"],
        }
        for symbol, value in report["assets"].items()
    }, indent=2))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
