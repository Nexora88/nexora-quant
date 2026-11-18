#!/usr/bin/env python3
"""Run event-time, multi-symbol PAPER research replay over captured gzip JSONL.

Each symbol is evaluated as the tradable instrument while BTC/ETH update the
macro context on the same timestamp-ordered timeline. A validated point-in-time
copy is made first so all symbol runs use a consistent input snapshot.
No exchange orders are created.
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.l2_backtest import L2BacktestConfig, run_l2_backtest, summarize_l2_result
from app.market_history import replay_market_history


def _snapshot_file(source: Path, destination: Path) -> dict:
    """Copy an actively appended gzip history and validate it before replay."""
    last_error: Exception | None = None
    for attempt in range(5):
        shutil.copy2(source, destination)
        try:
            counts: dict[str, int] = {}
            first = last = None
            for row in replay_market_history(destination):
                timestamp = int(row["timestamp_ns"])
                first = timestamp if first is None else first
                last = timestamp
                event_type = str(row["event_type"])
                counts[event_type] = counts.get(event_type, 0) + 1
            return {
                "first_timestamp_ns": first,
                "last_timestamp_ns": last,
                "event_counts": counts,
                "bytes": destination.stat().st_size,
            }
        except Exception as exc:
            last_error = exc
            time.sleep(0.25 * (attempt + 1))
    raise RuntimeError(f"Could not create a consistent snapshot of {source}: {last_error}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    root = Path(__file__).resolve().parents[1]
    data_dir = root / "data"
    configured_primary = Path(settings.market_history_path)
    if not configured_primary.is_absolute():
        configured_primary = root / configured_primary

    paths: dict[str, Path] = {}
    # Discover every recorded symbol, not only today's watch-list. This lets
    # historical altcoin files remain testable after the live universe changes.
    for candidate in data_dir.glob("market-history*.jsonl.gz"):
        if candidate.name == "market-history.jsonl.gz":
            symbol = settings.symbol.lower()
            if configured_primary.is_file():
                candidate = configured_primary
        elif candidate.name.startswith("market-history-"):
            symbol = candidate.name[len("market-history-"):-len(".jsonl.gz")].lower()
        else:
            continue
        if symbol and candidate.is_file() and candidate.stat().st_size > 0:
            paths[symbol] = candidate
    if configured_primary.is_file():
        paths[settings.symbol.lower()] = configured_primary

    if not paths:
        raise SystemExit("No market history files found. Start scripts/capture_multi_symbol.py first.")

    cfg = L2BacktestConfig(
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

    report = {
        "mode": "research_replay_only",
        "portfolio_mode": "independent_single_symbol_runs_with_shared_btc_eth_context",
        "starting_cash_per_symbol_usdt": cfg.starting_cash_usdt,
        "fee_rate": cfg.fee_rate,
        "slippage_bps_per_side": cfg.slippage_bps,
        "latency_ms": cfg.latency_ms,
        "snapshot_created_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbols_found": sorted(paths),
        "history_ranges": {},
        "results": {},
    }

    with tempfile.TemporaryDirectory(prefix="nexora-replay-") as temporary:
        snapshot_dir = Path(temporary)
        snapshot_paths: dict[str, Path] = {}
        for symbol, source in sorted(paths.items()):
            destination = snapshot_dir / f"{symbol}.jsonl.gz"
            stats = _snapshot_file(source, destination)
            snapshot_paths[symbol] = destination
            report["history_ranges"][symbol] = stats
            logging.info(
                "Snapshot validated %s bytes=%s events=%s",
                symbol.upper(), stats["bytes"], stats["event_counts"],
            )

        for symbol, primary_path in sorted(snapshot_paths.items()):
            # Only BTC and ETH are live macro references; unrelated altcoin books
            # are replayed as their own primary runs, not mixed into this symbol's gates.
            contexts = {
                s: p for s, p in snapshot_paths.items()
                if s in {"btcusdt", "ethusdt"} and s != symbol
            }
            result = run_l2_backtest(
                primary_path,
                cfg,
                context_paths=contexts,
                primary_symbol=symbol,
            )
            summary = summarize_l2_result(result)
            summary["source_files"] = {
                "primary": str(paths[symbol].relative_to(root)),
                "context": {s: str(paths[s].relative_to(root)) for s in contexts},
            }
            report["results"][symbol] = summary
            logging.info(
                "%s entries=%s exits=%s net_realized=%.4f return=%.3f%% max_dd=%.3f%% blockers=%s",
                symbol.upper(), summary["entries"], summary["exits"],
                summary["realized_pnl"], summary["return_pct"],
                summary["max_drawdown_pct"], summary["blocker_counts"],
            )

    report_dir = root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    output = report_dir / "multi_symbol_replay_latest.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    logging.info("Replay report written: %s", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
