from __future__ import annotations

import asyncio
import json

from app import binance_depth


class FakeSocket:
    def __init__(self, events):
        self.events = list(events)

    async def recv(self):
        await asyncio.sleep(1.0)
        raise asyncio.TimeoutError()

    def __aiter__(self):
        async def iterator():
            for event in self.events:
                yield json.dumps(event)
        return iterator()


class FakeConnection:
    def __init__(self, socket):
        self.socket = socket

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, *_):
        return False


def test_depth_stream_takes_new_snapshot_after_sequence_gap(monkeypatch):
    snapshots = iter([
        {"lastUpdateId": 100, "bids": [["99", "2"]], "asks": [["101", "2"]]},
        {"lastUpdateId": 200, "bids": [["199", "3"]], "asks": [["201", "3"]]},
    ])
    snapshot_calls = []

    def fake_snapshot(symbol):
        snapshot_calls.append(symbol)
        return next(snapshots)

    gap_event = {
        "e": "depthUpdate", "U": 105, "u": 106, "pu": 100,
        "b": [["100", "1"]], "a": [],
    }
    sockets = iter([FakeSocket([gap_event]), FakeSocket([])])

    monkeypatch.setattr(binance_depth, "_snapshot", fake_snapshot)
    monkeypatch.setattr(binance_depth.websockets, "connect", lambda *a, **k: FakeConnection(next(sockets)))
    monkeypatch.setattr(binance_depth.random, "uniform", lambda *_: 0.0)

    reconnects = []

    def on_reconnect(symbol, exc):
        reconnects.append((symbol, type(exc).__name__))

    async def scenario():
        stream = binance_depth.stream_synchronized_depth(
            "btcusdt", on_reconnect=on_reconnect,
        )
        first = await anext(stream)
        assert first.last_update_id == 100
        second = await anext(stream)
        assert second.last_update_id == 200
        assert second.best_bid == (199.0, 3.0)
        assert snapshot_calls == ["btcusdt", "btcusdt"]
        assert reconnects == [("btcusdt", "RuntimeError")]
        await stream.aclose()

    asyncio.run(scenario())


def test_spot_depth_stream_accepts_sequential_events_without_futures_pu(monkeypatch):
    snapshot_calls = []

    def fake_snapshot(symbol):
        snapshot_calls.append(symbol)
        return {"lastUpdateId": 100, "bids": [["99", "2"]], "asks": [["101", "2"]]}

    events = [
        {"e": "depthUpdate", "U": 100, "u": 102, "b": [["100", "1"]], "a": []},
        {"e": "depthUpdate", "U": 102, "u": 104, "b": [["100", "2"]], "a": []},
    ]
    socket = FakeSocket(events)
    monkeypatch.setattr(binance_depth, "_snapshot", fake_snapshot)
    monkeypatch.setattr(binance_depth.websockets, "connect", lambda *a, **k: FakeConnection(socket))

    async def scenario():
        stream = binance_depth.stream_synchronized_depth("btcusdt")
        initial = await anext(stream)
        initial_id = initial.last_update_id
        first = await anext(stream)
        first_id = first.last_update_id
        second = await anext(stream)
        second_id = second.last_update_id
        assert initial_id == 100
        assert first_id == 102
        assert second_id == 104
        assert second.best_bid == (100.0, 2.0)
        assert snapshot_calls == ["btcusdt"]
        await stream.aclose()

    asyncio.run(scenario())
