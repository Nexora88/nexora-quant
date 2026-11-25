import gzip
import json
from pathlib import Path

import pytest

import app.l2_backtest as replay
from app.l2_backtest import L2BacktestConfig, run_l2_backtest, summarize_l2_result
from app.simulation import market_impact_bps


def _write_fixture(path: Path, n: int = 40) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for i in range(n):
            mid = 100.0
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
    records = []

    # Closed-candle warmup mirrors the live EMA200 / multi-timeframe prerequisite.
    base_ms = base_ns // 1_000_000
    for interval, count, step_ms in (("1m", 250, 60_000), ("5m", 100, 300_000)):
        for i in range(count):
            close = 90.0 + i * 0.04
            records.append({
                "timestamp_ns": base_ns,
                "event_type": "kline",
                "payload": {
                    "symbol": "btcusdt", "interval": interval,
                    "open_time": base_ms - (count - i) * step_ms,
                    "open": close, "high": close + 0.03, "low": close - 0.01,
                    "close": close, "volume": 100.0, "closed": True,
                },
            })

    # Aggressive buy flow remains fresh at the expected entry time.
    for i in range(24):
        records.append({
            "timestamp_ns": base_ns + 100_000_000 + i * 50_000_000,
            "event_type": "trade",
            "payload": {
                "symbol": "btcusdt", "price": 100.0, "quantity": 0.1,
                "buyer_is_maker": False,
            },
        })

    # Slow enough to retain overlapping visible levels; then a controlled pullback.
    for i in range(200):
        mid = 100.0 + i * 0.008 if i <= 120 else 100.96 - (i - 120) * 0.01
        bid, ask = mid - 0.01, mid + 0.01
        bids = [[round(bid - j * 0.01, 2), 20.0 if j == 0 else 5.0] for j in range(20)]
        asks = [[round(ask + j * 0.01, 2), 2.0 if j == 0 else 3.0] for j in range(20)]
        records.append({
            "timestamp_ns": base_ns + 100_000_000 + i * 100_000_000,
            "event_type": "depth",
            "payload": {
                "symbol": "btcusdt",
                "best_bid": [bid, 20.0],
                "best_ask": [ask, 2.0],
                "bids": bids,
                "asks": asks,
            },
        })

    records.sort(key=lambda row: row["timestamp_ns"])
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for record in records:
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
        primary_symbol="btcusdt",
    )
    assert result.entries >= 1
    assert result.profit_lock_exits >= 1
    lock_exits = [
        trade for trade in result.trades
        if trade["side"] == "sell" and "l2_trailing_stop" in trade["reason"]
    ]
    assert lock_exits


def test_l2_replay_merges_context_symbols_by_event_timestamp(tmp_path):
    primary = tmp_path / "btc.jsonl.gz"
    context = tmp_path / "eth.jsonl.gz"
    base_ns = 1_700_000_000_000_000_000
    with gzip.open(primary, "wt", encoding="utf-8") as stream:
        stream.write(json.dumps({
            "timestamp_ns": base_ns + 200_000_000,
            "event_type": "depth",
            "payload": {
                "symbol": "btcusdt", "best_bid": [99.99, 10],
                "best_ask": [100.01, 10],
                "bids": [[99.99, 10]], "asks": [[100.01, 10]],
            },
        }) + "\n")
    with gzip.open(context, "wt", encoding="utf-8") as stream:
        stream.write(json.dumps({
            "timestamp_ns": base_ns,
            "event_type": "trade",
            "payload": {
                "symbol": "ethusdt", "price": 2000.0,
                "quantity": 0.1, "buyer_is_maker": False,
            },
        }) + "\n")
        stream.write(json.dumps({
            "timestamp_ns": base_ns + 100_000_000,
            "event_type": "kline",
            "payload": {
                "symbol": "ethusdt", "interval": "1m",
                "open_time": base_ns // 1_000_000 - 60_000,
                "open": 2000, "high": 2001, "low": 1999,
                "close": 2000, "volume": 100, "closed": True,
            },
        }) + "\n")

    result = run_l2_backtest(
        primary, context_paths={"ethusdt": context}, primary_symbol="btcusdt",
    )
    assert result.events_seen == 3
    assert result.trade_events == 0
    assert result.context_trade_events == 1
    assert result.kline_events == 1
    assert len(result.equity_curve) == 2


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



def test_l2_replay_marks_open_position_without_fabricating_final_trade(tmp_path):
    path = tmp_path / "end-mark.jsonl.gz"
    base_ns = 1_700_000_000_000_000_000
    base_ms = base_ns // 1_000_000
    records = []
    for interval, count, step_ms in (("1m", 250, 60_000), ("5m", 100, 300_000)):
        for i in range(count):
            close = 90.0 + i * 0.04
            records.append({
                "timestamp_ns": base_ns,
                "event_type": "kline",
                "payload": {
                    "symbol": "btcusdt", "interval": interval,
                    "open_time": base_ms - (count - i) * step_ms,
                    "open": close, "high": close + 0.03, "low": close - 0.01,
                    "close": close, "volume": 100.0, "closed": True,
                },
            })
    for i in range(24):
        records.append({
            "timestamp_ns": base_ns + 100_000_000 + i * 50_000_000,
            "event_type": "trade",
            "payload": {
                "symbol": "btcusdt", "price": 100.0,
                "quantity": 0.1, "buyer_is_maker": False,
            },
        })
    bids = [[99.99 - i * 0.01, 20.0 if i == 0 else 5.0] for i in range(20)]
    asks = [[100.01 + i * 0.01, 2.0 if i == 0 else 3.0] for i in range(20)]
    for i in range(40):
        records.append({
            "timestamp_ns": base_ns + 100_000_000 + i * 100_000_000,
            "event_type": "depth",
            "payload": {
                "symbol": "btcusdt", "best_bid": [99.99, 20.0],
                "best_ask": [100.01, 2.0], "bids": bids, "asks": asks,
            },
        })
    records.sort(key=lambda row: row["timestamp_ns"])
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record) + "\n")

    result = run_l2_backtest(
        path,
        L2BacktestConfig(
            signal_confirmations=2, entry_min_score=0.4,
            take_profit_pct=50, stop_loss_pct=50, trailing_stop_pct=0,
            slippage_bps=0, impact_coefficient=0, latency_ms=0,
        ),
        primary_symbol="btcusdt",
    )
    assert result.entries >= 1
    assert result.final_open_quantity > 0
    assert result.closed_positions == 0
    assert result.exits == 0
    assert result.trades[-1]["side"] == "buy"
    assert summarize_l2_result(result)["ending_valuation"] == "mark_to_observed_bid_no_forced_close"
    assert result.final_equity == pytest.approx(result.final_cash + 99.99 * result.final_open_quantity)


def _execution_replay(tmp_path, monkeypatch, records, *, exit_when=None, **overrides):
    monkeypatch.setattr(replay, "entry_signal_from_analysis", lambda *a, **k: True)
    monkeypatch.setattr(replay.ReplayMarketContext, "entry_blockers", lambda *a: ([], {}))
    monkeypatch.setattr(replay.ExecutionSimulator, "sample_latency_ms", lambda self, **kw: self.latency_ms)
    if exit_when is not None:
        monkeypatch.setattr(replay, "exit_reason", lambda **kw: "take_profit" if exit_when(kw["bid"]) else None)
    path = tmp_path / "events.jsonl"
    path.write_text(
        "\n".join(json.dumps({
            "timestamp_ns": ms * 1_000_000,
            "event_type": "depth",
            "payload": {"symbol": "btcusdt", "bids": [[bid, 10]], "asks": asks, **extra},
        }) for ms, bid, asks, extra in records) + "\n",
        encoding="utf-8",
    )
    params = {
        "latency_ms": 100, "signal_confirmations": 1, "slippage_bps": 0, "impact_coefficient": 0,
        "fee_rate": 0, "take_profit_pct": 1000, "stop_loss_pct": 100, "trailing_stop_pct": 0,
        **overrides,
    }
    return run_l2_backtest(path, L2BacktestConfig(**params), primary_symbol="btcusdt")


def test_replay_fills_on_eligible_observed_book_and_caps_quote_budget(tmp_path, monkeypatch):
    res = _execution_replay(tmp_path, monkeypatch, [
        (0, 99, [[100, 10]], {}),
        (50, 109, [[110, 10]], {}),
        (200, 119, [[120, 10]], {}),
    ])
    assert len(res.trades) == 1
    trade = res.trades[0]
    assert trade["decision_timestamp_ns"] == 0
    assert trade["arrival_timestamp_ns"] == 100_000_000
    assert trade["timestamp_ns"] == 200_000_000
    assert trade["price"] == 120
    assert trade["notional_usdt"] == 25
    assert trade["quantity"] == pytest.approx(25 / 120)


def test_replay_sell_uses_later_bid_not_trigger_bid(tmp_path, monkeypatch):
    res = _execution_replay(tmp_path, monkeypatch, [
        (0, 99, [[100, 10]], {}),
        (100, 99, [[100, 10]], {}),
        (200, 110, [[111, 10]], {}),
        (250, 112, [[113, 10]], {}),
        (300, 105, [[106, 10]], {}),
    ], exit_when=lambda bid: bid >= 110)
    assert res.closed_positions == 1
    assert res.trades[1]["price"] == 105
    assert res.trades[1]["decision_timestamp_ns"] == 200_000_000
    assert res.trades[1]["timestamp_ns"] == 300_000_000


def test_replay_does_not_invent_depth_for_thin_book(tmp_path, monkeypatch):
    res = _execution_replay(tmp_path, monkeypatch, [
        (0, 99, [[100, 10]], {}),
        (100, 100, [[101, 0.001]], {}),
    ])
    assert res.trades[0]["quantity"] == pytest.approx(0.001)


@pytest.mark.parametrize("second", [
    (200, 119, [], {"best_ask": [120, 20]}),
    (200, 119, [[120, 10]], {"synchronized": False}),
    (200, 119, [[120, 10], [120, 10]], {}),
    (5000, 119, [[120, 10]], {}),
])
def test_replay_missing_invalid_or_too_late_depth_does_not_fill(tmp_path, monkeypatch, second):
    res = _execution_replay(tmp_path, monkeypatch, [(0, 99, [[100, 10]], {}), second])
    assert res.trades == []
    assert res.unfilled_orders == 1
    assert res.pending_orders_at_end == 0


def test_replay_ending_before_arrival_reports_pending_not_fill(tmp_path, monkeypatch):
    res = _execution_replay(tmp_path, monkeypatch, [(0, 99, [[100, 10]], {})])
    assert res.trades == []
    assert res.pending_orders_at_end == 1
