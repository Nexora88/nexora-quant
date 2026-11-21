from __future__ import annotations
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter

from dotenv import load_dotenv
load_dotenv(".env.paper-20min", override=True)

from app.config import settings  # noqa: E402  # .env must load before settings
from app.market_history import replay_market_history  # noqa: E402
from app.l2_backtest import L2BacktestConfig, run_l2_backtest, summarize_l2_result  # noqa: E402

settings.validate()
source = Path(settings.market_history_path)
if not source.is_absolute():
    source = Path.cwd() / source
if not source.is_file() or source.stat().st_size <= 0:
    raise SystemExit(f"20-minute market history not yet available: {source}")

counts = Counter()
first_ts = last_ts = None
for row in replay_market_history(source):
    ts = int(row["timestamp_ns"])
    first_ts = ts if first_ts is None else first_ts
    last_ts = ts
    counts[row["event_type"]] += 1
if not counts:
    raise SystemExit("No validated market events were recorded; refusing to recommend a threshold.")

base = L2BacktestConfig(
    starting_cash_usdt=settings.starting_cash_usdt,
    fee_rate=settings.effective_fee_rate(),
    order_size_usdt=settings.order_size_usdt,
    max_order_size_usdt=settings.max_order_size_usdt,
    imbalance_threshold=settings.imbalance_threshold,
    entry_min_score=settings.entry_min_score,
    signal_confirmations=settings.signal_confirmations,
    take_profit_pct=settings.take_profit_pct,
    stop_loss_pct=settings.stop_loss_pct,
    trailing_stop_pct=settings.trailing_stop_pct,
    target_price=settings.target_price,
    slippage_bps=settings.simulated_slippage_bps,
    impact_coefficient=settings.impact_coefficient,
    latency_ms=settings.simulated_latency_ms,
    partial_fill_probability=settings.simulated_partial_fill_probability,
    seed=settings.simulation_seed,
    min_order_usdt=settings.min_order_usdt,
    stop_stress_multiplier=settings.stop_stress_multiplier,
    stop_tail_bps=settings.stop_tail_bps,
)
thresholds = (0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60)
sweep = []
for threshold in thresholds:
    cfg = replace(base, entry_min_score=threshold)
    result = run_l2_backtest(source, cfg, primary_symbol=settings.symbol)
    summary = summarize_l2_result(result)
    sweep.append({"entry_min_score": threshold, **summary})
    print(
        f"threshold={threshold:.2f} events={summary['events_seen']} "
        f"signals={summary['signals']} entries={summary['entries']} exits={summary['exits']} "
        f"closed={summary['closed_position_count']} net_pnl={summary['realized_pnl']:.6f} "
        f"fees={summary['fees_paid_usdt']:.6f} dd={summary['max_drawdown_pct']:.4f}%"
    )

eligible = [
    row for row in sweep
    if row["closed_position_count"] >= 10
    and row["expectancy_usdt_per_exit_fill"] > 0
    and (row["profit_factor_per_exit_fill"] or 0) > 1.2
    and row["max_drawdown_pct"] < 8.0
]
recommendation = None
if eligible:
    recommendation = max(
        eligible,
        key=lambda row: (
            row["expectancy_usdt_per_exit_fill"],
            row["profit_factor_per_exit_fill"] or 0,
            -row["max_drawdown_pct"],
        ),
    )["entry_min_score"]

report = {
    "mode": "paper_research_replay_only",
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "source_file": str(source),
    "source_bytes": source.stat().st_size,
    "event_counts": dict(counts),
    "first_event_utc": datetime.fromtimestamp(first_ts / 1e9, timezone.utc).isoformat(),
    "last_event_utc": datetime.fromtimestamp(last_ts / 1e9, timezone.utc).isoformat(),
    "starting_cash_usdt": base.starting_cash_usdt,
    "fee_rate": base.fee_rate,
    "slippage_bps_per_side": base.slippage_bps,
    "latency_ms": base.latency_ms,
    "thresholds": sweep,
    "eligibility_rule": {
        "minimum_closed_positions": 10,
        "minimum_expectancy_usdt": "> 0",
        "minimum_profit_factor": "> 1.2",
        "maximum_drawdown_pct": "< 8",
    },
    "recommended_threshold": recommendation,
    "conclusion": (
        "No threshold selected: insufficient qualifying closed trades or no threshold passed all criteria."
        if recommendation is None else
        "Candidate only; validate on longer, unseen windows before changing the production threshold."
    ),
    "limitations": [
        "This is a deterministic L2 replay, not live execution.",
        "The current recorder stores primary-symbol depth events; true queue priority, hidden liquidity and exact fills are not observable.",
        "A 20-minute sample is exploratory and cannot establish durable profitability.",
    ],
}
out = Path("reports/paper-20min-threshold-sweep-20261121.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
print(f"REPORT={out}")
print(f"RECOMMENDED_THRESHOLD={recommendation}")
