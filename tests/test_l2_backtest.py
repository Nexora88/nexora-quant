import gzip
import json
from pathlib import Path

from app.l2_backtest import L2BacktestConfig, run_l2_backtest, summarize_l2_result
from app.simulation import market_impact_bps


def _write_fixture(path: Path, n: int = 40) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for i in range(n):
            mid = 100 + i * 0.05
            bid, ask = mid - 0.01, mid + 0.01
            bid_qty = 20 if i > 5 else 5
            ask_qty = 2 if i > 5 else 5
            rec = {
                "timestamp_ns": 1_700_000_000_000_000_000 + i * 100_000_000,
                "event_type": "depth",
                "payload": {
                    "symbol": "btcusdt",
                    "best_bid": [bid, bid_qty],
                    "best_ask": [ask, ask_qty],
                    "bids": [[bid, bid_qty], [bid - 0.05, 3]],
                    "asks": [[ask, ask_qty], [ask + 0.05, 3]],
                },
            }
            f.write(json.dumps(rec) + "\n")


def test_l2_backtest_runs_on_history_fixture(tmp_path):
    path = tmp_path / "hist.jsonl.gz"
    _write_fixture(path)
    result = run_l2_backtest(
        path,
        L2BacktestConfig(
            signal_confirmations=2,
            entry_min_score=0.4,
            take_profit_pct=50,
            stop_loss_pct=50,
            trailing_stop_pct=0,
            latency_ms=0,
        ),
    )
    summary = summarize_l2_result(result)
    assert result.events_seen == 40
    assert summary["events_seen"] == 40
    assert result.signals >= 1


def test_market_impact_grows_with_participation():
    small = market_impact_bps(notional_usdt=100, visible_liquidity_usdt=10_000, coefficient=0.1)
    large = market_impact_bps(notional_usdt=5_000, visible_liquidity_usdt=10_000, coefficient=0.1)
    assert large > small > 0
