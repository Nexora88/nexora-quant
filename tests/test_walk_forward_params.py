import json
from pathlib import Path

from scripts import walk_forward_params as wf


def test_walk_forward_selects_on_train_and_never_reranks_test(monkeypatch, tmp_path: Path):
    calls = []

    def fake_backtest(path, config):
        calls.append((Path(path).name, config.entry_min_score, config.fee_rate))
        if Path(path).name == "train.jsonl":
            score = 1.0 if config.entry_min_score == 0.2 else 5.0
        else:
            score = 100.0 if config.entry_min_score == 0.2 else -20.0
        return {"return_pct": score, "realized_pnl": score, "closed_position_count": 2}

    monkeypatch.setattr(wf, "run_l2_backtest", fake_backtest)
    monkeypatch.setattr(wf, "summarize_l2_result", lambda result: result)

    report = wf.evaluate_train_then_test(
        tmp_path / "train.jsonl",
        tmp_path / "test.jsonl",
        candidates=[
            {"entry_min_score": 0.2},
            {"entry_min_score": 0.8},
        ],
        fee_rate=0.002,
    )

    assert report["selected_params"]["entry_min_score"] == 0.8
    assert report["unseen_test_metrics"]["return_pct"] == -20.0
    assert len(calls) == 3  # two training runs, exactly one unseen test run
    assert all(fee == 0.002 for _, _, fee in calls)
    assert calls[-1] == ("test.jsonl", 0.8, 0.002)


def test_history_split_preserves_order_and_rejects_bad_fraction(tmp_path: Path):
    source = tmp_path / "history.jsonl"
    source.write_text(
        "".join(json.dumps({"n": i, "timestamp_ns": i}) + "\n" for i in range(250)),
        encoding="utf-8",
    )
    train, test = wf._split_history(source, 0.7, embargo_seconds=0)
    train_rows = [json.loads(line)["n"] for line in train.read_text().splitlines()]
    test_rows = [json.loads(line)["n"] for line in test.read_text().splitlines()]
    assert train_rows[-1] < test_rows[0]
    assert train_rows == list(range(175))
    assert test_rows == list(range(175, 250))

    try:
        wf._split_history(source, 1.0)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid train fraction must be rejected")


def test_l2_walk_forward_uses_risk_adjusted_training_selection_and_no_trade_fallback(monkeypatch, tmp_path):
    def fake_backtest(path, config):
        if Path(path).name == "train.jsonl":
            if config.entry_min_score == 0.2:
                return {"return_pct": 12.0, "realized_pnl": 12.0, "closed_position_count": 2, "max_drawdown_pct": 30.0}
            return {"return_pct": 8.0, "realized_pnl": 8.0, "closed_position_count": 2, "max_drawdown_pct": 4.0}
        return {"return_pct": -1.0, "max_drawdown_pct": 2.0}

    monkeypatch.setattr(wf, "run_l2_backtest", fake_backtest)
    monkeypatch.setattr(wf, "summarize_l2_result", lambda result: result)
    report = wf.evaluate_train_then_test(
        tmp_path / "train.jsonl", tmp_path / "test.jsonl",
        candidates=[{"entry_min_score": 0.2}, {"entry_min_score": 0.8}],
    )
    assert report["selected_params"]["entry_min_score"] == 0.8
    assert report["no_trade_fallback"] is False

    def losing_backtest(path, config):
        return {"return_pct": -2.0, "realized_pnl": -2, "closed_position_count": 2, "max_drawdown_pct": 5.0}
    monkeypatch.setattr(wf, "run_l2_backtest", losing_backtest)
    report = wf.evaluate_train_then_test(
        tmp_path / "train.jsonl", tmp_path / "test.jsonl",
        candidates=[{"entry_min_score": 0.2}, {"entry_min_score": 0.8}],
    )
    assert report["no_trade_fallback"] is True
    assert report["selected_params"]["entry_min_score"] > 1.0


def test_unrealized_training_winner_without_round_trip_is_not_selected(monkeypatch, tmp_path):
    monkeypatch.setattr(wf, "summarize_l2_result", lambda result: result)
    monkeypatch.setattr(wf, "run_l2_backtest", lambda path, config: {
        "return_pct": 12.0, "realized_pnl": 0.0, "closed_position_count": 0,
    })
    result = wf.evaluate_train_then_test(tmp_path / "train.jsonl", tmp_path / "test.jsonl")
    assert result["no_trade_fallback"]
    assert result["candidate_training_metrics"][0]["metrics"]["selection_score"] is None


def test_walk_forward_split_files_are_replayable_by_real_l2_backtest(tmp_path):
    import gzip
    from app.l2_backtest import L2BacktestConfig, run_l2_backtest

    source = tmp_path / "captured.jsonl.gz"
    with gzip.open(source, "wt", encoding="utf-8") as stream:
        for i in range(250):
            mid = 100 + i * 0.001
            row = {
                "timestamp_ns": 1_700_000_000_000_000_000 + i * 100_000_000,
                "event_type": "depth",
                "payload": {
                    "best_bid": [mid - 0.01, 10], "best_ask": [mid + 0.01, 2],
                    "bids": [[mid - 0.01, 10]], "asks": [[mid + 0.01, 2]],
                },
            }
            stream.write(json.dumps(row) + "\n")
    train, test = wf._split_history(source, 0.7, embargo_seconds=0)
    assert train.suffix == ".jsonl" and test.suffix == ".jsonl"
    train_result = run_l2_backtest(train, L2BacktestConfig(signal_confirmations=1))
    test_result = run_l2_backtest(test, L2BacktestConfig(signal_confirmations=1))
    assert train_result.events_seen == 175
    assert test_result.events_seen == 75
