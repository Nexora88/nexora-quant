"""Reproducible multi-asset walk-forward evaluation for OHLCV CSV files.

This produces historical research evidence, not a forecast or profitability guarantee.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.backtesting import BacktestConfig, load_ohlcv_csv, validate_multiple_assets


CANDIDATES = [
    {"strategy": "buy_and_hold", "params": {}},
    {"strategy": "momentum", "params": {"lookback": 5}},
    {"strategy": "momentum", "params": {"lookback": 10}},
    {"strategy": "momentum", "params": {"lookback": 20}},
    {"strategy": "sma_cross", "params": {"fast": 5, "slow": 20}},
    {"strategy": "sma_cross", "params": {"fast": 10, "slow": 30}},
    {"strategy": "mean_reversion", "params": {"window": 20, "entry_z": 1.5}},
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True,
                        help="directory containing one chronological OHLCV CSV per asset")
    parser.add_argument("--output", type=Path, default=Path("profitability-report.json"))
    parser.add_argument("--train-bars", type=int, default=500)
    parser.add_argument("--test-bars", type=int, default=100)
    parser.add_argument("--fee-rate", type=float, default=0.001)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--latency-bars", type=int, default=1)
    args = parser.parse_args()

    files = sorted(args.data_dir.glob("*.csv"))
    if len(files) < 2:
        parser.error("at least two separate asset CSV files are required")
    if args.train_bars < 100 or args.test_bars < 20:
        parser.error("use at least 100 training bars and 20 test bars per window")

    datasets = {path.stem.upper(): load_ohlcv_csv(path) for path in files}
    required = args.train_bars + args.test_bars
    short = {symbol: len(rows) for symbol, rows in datasets.items() if len(rows) < required}
    if short:
        parser.error(f"insufficient candles; need at least {required} per asset: {short}")

    config = BacktestConfig(
        fee_rate=args.fee_rate,
        slippage_bps=args.slippage_bps,
        latency_bars=args.latency_bars,
        min_train_bars=min(100, args.train_bars),
    ).validate()
    report = validate_multiple_assets(
        datasets, CANDIDATES,
        train_bars=args.train_bars,
        test_bars=args.test_bars,
        config=config,
    )
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "assets": sorted(datasets),
        "candles_per_asset": {symbol: len(rows) for symbol, rows in datasets.items()},
        "cost_assumptions": {
            "fee_rate_per_side": args.fee_rate,
            "slippage_bps": args.slippage_bps,
            "latency_bars": args.latency_bars,
        },
        "method": "rolling chronological walk-forward; no concatenation across assets",
        "report": report,
        "interpretation": (
            "Historical results only. Positive windows do not establish future profitability. "
            "Review out-of-sample dispersion, worst-window returns, drawdowns, sample size, "
            "data quality, spread, partial fills, market impact, and independent holdouts."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote research report to {args.output}")
    print(json.dumps({
        "asset_count": report["asset_count"],
        "worst_asset_window_return_pct": report["worst_asset_window_return_pct"],
        "worst_asset_max_drawdown_pct": report["worst_asset_max_drawdown_pct"],
        "warning": "This is not proof or a guarantee of profitability.",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
