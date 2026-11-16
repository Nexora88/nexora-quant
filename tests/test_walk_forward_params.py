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
        return {"return_pct": score}

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
        "".join(f'{{"n": {i}}}\n' for i in range(250)),
        encoding="utf-8",
    )
    train, test = wf._split_history(source, 0.7)
    train_rows = [int(line.split(":")[1].strip(" }")) for line in train.read_text().splitlines()]
    test_rows = [int(line.split(":")[1].strip(" }")) for line in test.read_text().splitlines()]
    assert train_rows[-1] < test_rows[0]
    assert train_rows == list(range(175))
    assert test_rows == list(range(175, 250))

    try:
        wf._split_history(source, 1.0)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid train fraction must be rejected")
