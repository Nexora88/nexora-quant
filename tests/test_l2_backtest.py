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
    # Every valid depth event marks the account, including time spent holding risk.
    assert len(result.equity_curve) == result.events_seen + 1
    assert result.equity_curve[0]["phase"] == "initial"
    assert result.equity_curve[0]["equity"] == 1000.0
    assert "max_drawdown_pct" in summary
    assert "fees_paid_usdt" in summary
    assert summary["exit_fill_count"] == result.exits
    assert summary["closed_position_count"] <= summary["exit_fill_count"]


def test_market_impact_grows_with_participation():
    small = market_impact_bps(notional_usdt=100, visible_liquidity_usdt=10_000, coefficient=0.1)
    large = market_impact_bps(notional_usdt=5_000, visible_liquidity_usdt=10_000, coefficient=0.1)
    assert large > small > 0


def test_l2_replay_applies_fee_aware_profit_lock_after_peak_giveback(tmp_path):
    path = tmp_path / "profit-lock.jsonl.gz"
    base_ns = 1_700_000_000_000_000_000
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for i in range(26):
            mid = 100.0 + i * 0.08 if i <= 14 else 101.12 - (i - 14) * 0.12
            bid, ask = mid - 0.01, mid + 0.01
            record = {
                "timestamp_ns": base_ns + i * 100_000_000,
                "event_type": "depth",
                "payload": {
                    "symbol": "btcusdt",
                    "best_bid": [bid, 20.0],
                    "best_ask": [ask, 2.0],
                    "bids": [[bid, 20.0], [bid - 0.05, 5.0]],
                    "asks": [[ask, 2.0], [ask + 0.05, 2.0]],
                },
            }
            stream.write(json.dumps(record) + "\n")

    result = run_l2_backtest(
        path,
        L2BacktestConfig(
            signal_confirmations=2,
            entry_min_score=0.4,
            take_profit_pct=50,
            stop_loss_pct=50,
            trailing_stop_pct=0,
            slippage_bps=0,
            impact_coefficient=0,
            latency_ms=0,
        ),
    )
    assert result.entries >= 1
    assert result.profit_lock_exits >= 1
    lock_exits = [
        trade for trade in result.trades
        if trade["side"] == "sell" and "l2_trailing_stop" in trade["reason"]
    ]
    assert lock_exits


def test_l2_replay_consumes_trade_and_closed_kline_events(tmp_path):
    path = tmp_path / "mixed-events.jsonl.gz"
    base_ns = 1_700_000_000_000_000_000
    records = []
    for interval, count, step_ms in (("1m", 3, 60_000), ("5m", 2, 300_000)):
        for i in range(count):
            price = 100.0 + i
            records.append({
                "timestamp_ns": base_ns,
                "event_type": "kline",
                "payload": {
                    "symbol": "btcusdt", "interval": interval,
                    "open_time": 1_699_999_000_000 + i * step_ms,
                    "open": price, "high": price + 1, "low": price - 1,
                    "close": price, "volume": 10.0, "closed": True,
                },
            })
    for i in range(20):
        records.append({
            "timestamp_ns": base_ns + (i + 1) * 10_000_000,
            "event_type": "trade",
            "payload": {
                "symbol": "btcusdt", "price": 100.0, "quantity": 0.01,
                "buyer_is_maker": bool(i % 2),
            },
        })
    records.append({
        "timestamp_ns": base_ns + 300_000_000,
        "event_type": "depth",
        "payload": {
            "symbol": "btcusdt", "best_bid": [99.99, 10],
            "best_ask": [100.01, 10],
            "bids": [[99.99, 10]], "asks": [[100.01, 10]],
        },
    })
    records.sort(key=lambda row: row["timestamp_ns"])
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record) + "\n")

    result = run_l2_backtest(path)
    assert result.trade_events == 20
    assert result.kline_events == 5
    assert result.events_seen == len(records)
