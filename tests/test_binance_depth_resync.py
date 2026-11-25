from __future__ import annotations

import asyncio
from contextlib import aclosing
import json
import time

import pytest

from app import binance_depth, binance_ws, market_indicators


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


@pytest.mark.parametrize("testnet", [False, True])
def test_public_depth_trades_and_candles_stay_on_the_selected_network(monkeypatch, testnet):
    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    http_urls = []
    ws_urls = []

    def urlopen(request, *, timeout):
        http_urls.append(request.full_url)
        if "/depth?" in request.full_url:
            return Response({"lastUpdateId": 100, "bids": [["99", "2"]], "asks": [["101", "2"]]})
        return Response([])

    def connect(url, **_):
        ws_urls.append(url)
        events = ([{"stream": "btcusdt@trade", "data": {
            "e": "trade", "s": "BTCUSDT", "p": "100", "q": "1", "m": False,
        }}] if "streams=" in url else [])
        return FakeConnection(FakeSocket(events))

    monkeypatch.setattr(binance_depth.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(binance_depth.websockets, "connect", connect)
    monkeypatch.setattr(binance_ws.websockets, "connect", connect)

    async def scenario():
        async with aclosing(binance_depth.stream_synchronized_depth("btcusdt", testnet=testnet)) as stream:
            depth = await anext(stream)
            assert depth.testnet is testnet
            assert depth.best_bid == (99.0, 2.0)
        async with aclosing(binance_ws.stream_events("btcusdt", testnet=testnet)) as stream:
            assert (await anext(stream)).price == 100.0

    asyncio.run(scenario())
    assert market_indicators.fetch_recent_candles("btcusdt", "1m", testnet=testnet) == []
    rest = "https://testnet.binance.vision" if testnet else "https://api.binance.com"
    ws = "wss://stream.testnet.binance.vision" if testnet else "wss://stream.binance.com:9443"
    assert [url.split("?")[0] for url in http_urls] == [f"{rest}/api/v3/depth", f"{rest}/api/v3/klines"]
    assert [url.split("?")[0] for url in ws_urls] == [f"{ws}/ws/btcusdt@depth@100ms", f"{ws}/stream"]


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
        {"e": "depthUpdate", "U": 100, "u": 102, "b": [["100", "999"]], "a": []},
        {"e": "depthUpdate", "U": 102, "u": 104, "b": [["100", "2"]], "a": [],
         "E": int(time.time() * 1000)},
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
        assert initial.best_bid == (99.0, 2.0)
        assert first.best_bid == (100.0, 1.0)
        assert second.best_bid == (100.0, 2.0)
        assert second.exchange_at_ms == events[-1]["E"]
        with pytest.raises(TypeError):
            first.bids[100.0] = 9.0
        assert snapshot_calls == ["btcusdt"]
        await stream.aclose()

    asyncio.run(scenario())


def test_resync_does_not_publish_same_revision_again(monkeypatch):
    replies = iter([
        {"lastUpdateId": 100, "bids": [["99", "2"]], "asks": [["101", "2"]]},
        {"lastUpdateId": 100, "bids": [["98", "2"]], "asks": [["101", "2"]]},
    ])
    resumable = {"e": "depthUpdate", "U": 101, "u": 101, "b": [["100", "1"]], "a": []}
    sockets = iter([FakeSocket([]), FakeSocket([resumable])])
    monkeypatch.setattr(binance_depth, "_snapshot", lambda _: next(replies))
    monkeypatch.setattr(binance_depth.websockets, "connect", lambda *a, **k: FakeConnection(next(sockets)))
    monkeypatch.setattr(binance_depth.random, "uniform", lambda *_: 0.0)

    async def scenario():
        stream = binance_depth.stream_synchronized_depth("btcusdt")
        try:
            assert (await anext(stream)).last_update_id == 100
            assert (await anext(stream)).last_update_id == 101
        finally:
            await stream.aclose()

    asyncio.run(scenario())
