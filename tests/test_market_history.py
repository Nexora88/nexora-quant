import gzip
import json

import pytest

from app.depth_book import DepthBook
from app.depth_metrics import depth_imbalance, liquidity_walls
from app.market_history import MarketHistoryWriter, replay_market_history


def test_compressed_history_round_trip_and_replay_order(tmp_path):
    path = tmp_path / "events.jsonl.gz"
    writer = MarketHistoryWriter(path)
    writer.append(timestamp_ns=10, event_type="depth", payload={"u": 1})
    writer.append(timestamp_ns=10, event_type="trade", payload={"price": 100.0})
    writer.append(timestamp_ns=20, event_type="depth", payload={"u": 2})

    records = list(replay_market_history(path))
    assert [row["timestamp_ns"] for row in records] == [10, 10, 20]
    assert [row["event_type"] for row in records] == ["depth", "trade", "depth"]


def test_writer_rejects_out_of_order_and_non_finite_payload(tmp_path):
    writer = MarketHistoryWriter(tmp_path / "events.gz")
    writer.append(timestamp_ns=5, event_type="depth", payload={})
    with pytest.raises(ValueError):
        writer.append(timestamp_ns=4, event_type="depth", payload={})
    with pytest.raises(ValueError):
        writer.append(timestamp_ns=6, event_type="depth", payload={"bad": float("nan")})


def test_replay_rejects_malformed_records(tmp_path):
    path = tmp_path / "bad.gz"
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        stream.write(json.dumps({"timestamp_ns": 2, "event_type": "depth", "payload": {}}) + "\n")
        stream.write(json.dumps({"timestamp_ns": 1, "event_type": "depth", "payload": {}}) + "\n")
    iterator = replay_market_history(path)
    next(iterator)
    with pytest.raises(ValueError, match="out-of-order"):
        next(iterator)


def test_multilevel_depth_metrics_and_unsynchronized_guard():
    book = DepthBook()
    assert depth_imbalance(book) is None
    book.load_snapshot(
        last_update_id=10,
        bids=[(100, 9), (99, 3), (98, 1)],
        asks=[(101, 2), (102, 2), (103, 2)],
    )
    assert depth_imbalance(book, levels=3) == pytest.approx(7 / 19)
    walls = liquidity_walls(book, levels=3, multiple=2)
    assert walls is not None
    assert walls["bids"][0]["price"] == 100
    book.synchronized = False
    assert depth_imbalance(book) is None
    assert liquidity_walls(book) is None


def test_metrics_validate_parameters():
    book = DepthBook()
    with pytest.raises(ValueError):
        depth_imbalance(book, levels=0)
    with pytest.raises(ValueError):
        liquidity_walls(book, multiple=1)
