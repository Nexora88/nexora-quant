import json
from hashlib import sha256

import pytest

from scripts.rolling_walk_forward import rolling_bounds, run_rolling_walk_forward


def test_rolling_windows_are_chronological_and_non_overlapping():
    bounds = rolling_bounds(1000, 3)
    assert len(bounds) == 3
    previous_test_end = None
    for train_end, test_start, test_end in bounds:
        assert train_end == test_start
        if previous_test_end is not None:
            assert train_end == previous_test_end
        assert test_end > test_start
        previous_test_end = test_end


def test_rolling_windows_reject_too_short_history():
    with pytest.raises(ValueError):
        rolling_bounds(100, 2)


def _history(path, *, timestamps):
    path.write_text("\n".join(json.dumps({
        "timestamp_ns": timestamp,
        "event_type": "depth",
        "payload": {"symbol": "btcusdt", "bids": [[100, 5]], "asks": [[101, 5]]},
    }) for timestamp in timestamps) + "\n", encoding="utf-8")


def test_run_rolling_uses_event_time_embargo_and_disjoint_timestamp_groups(tmp_path):
    path = tmp_path / "market-history-btcusdt.jsonl"
    _history(path, timestamps=[(i // 4) * 1_000_000_000 for i in range(600)])
    result = run_rolling_walk_forward({"btcusdt": path}, windows=2, embargo_seconds=10)
    windows = result["assets"]["btcusdt"]["windows"]
    for w in windows:
        assert w["test_first_timestamp_ns"] - w["train_last_timestamp_ns"] > 10_000_000_000
        assert w["omitted_events"] > 0
    assert windows[0]["test_last_timestamp_ns"] < windows[1]["test_first_timestamp_ns"]
    assert result["assets"]["btcusdt"]["positive_flat_windows"] == 0


def test_run_rolling_refuses_split_if_embargo_purges_training_data(tmp_path):
    path = tmp_path / "market-history-btcusdt.jsonl"
    _history(path, timestamps=[i * 1_000_000 for i in range(600)])
    with pytest.raises(ValueError, match="too small after time embargo"):
        run_rolling_walk_forward({"btcusdt": path})


def test_verified_walk_forward_binds_capture_to_symbol_and_archive(tmp_path):
    path = tmp_path / "btcusdt.jsonl"
    _history(path, timestamps=[i * 1_000_000_000 for i in range(600)])
    manifest = tmp_path / "manifest.json"
    digest = sha256(path.read_bytes()).hexdigest()
    manifest.write_text(json.dumps({
        "schema_version": 1, "source": "binance_spot_public", "research_only": True, "coverage_ok": True,
        "captures": [{"file": path.name, "coverage_ok": True, "symbol": "BTCUSDT", "sha256": digest}],
    }))
    report = run_rolling_walk_forward({"btcusdt": path}, capture_manifests={"btcusdt": manifest}, embargo_seconds=10)
    assert report["assets"]["btcusdt"]["verified_capture_sha256"] == digest
    assert len(report["source_fingerprint"]) == 64
    with pytest.raises(ValueError, match="symbol does not match"):
        run_rolling_walk_forward({"ethusdt": path}, capture_manifests={"ethusdt": manifest}, embargo_seconds=10)
    with path.open("ab") as output:
        output.write(b"\n")
    with pytest.raises(ValueError, match="hash"):
        run_rolling_walk_forward({"btcusdt": path}, capture_manifests={"btcusdt": manifest}, embargo_seconds=10)
