"""Multi-symbol watch list and fan-in helpers."""
from __future__ import annotations

import asyncio
import time

import pytest

from app import multi_stream
from app.depth_book import DepthBook
from app.multi_stream import watch_list


def _book(update_id):
    book = DepthBook(symbol="btcusdt")
    book.load_snapshot(last_update_id=update_id, bids=[(99, 2)], asks=[(101, 2)])
    return book.publish(received_at_ns=time.time_ns(), received_monotonic_ns=time.monotonic_ns())


@pytest.mark.asyncio
async def test_fan_in_drops_book_from_before_resync(monkeypatch):
    reports = []
    done = asyncio.Event()

    async def fake_stream(symbol, *, on_reconnect):
        yield _book(1)
        on_reconnect(symbol, RuntimeError("gap"))
        yield _book(3)
        await done.wait()

    monkeypatch.setattr(multi_stream, "stream_synchronized_depth", fake_stream)
    stream = multi_stream.stream_multi_depth(
        ["btcusdt"], on_drop=lambda symbol, reason: reports.append((symbol, reason)),
    )
    try:
        first = await asyncio.wait_for(anext(stream), timeout=1)
        assert first.book.last_update_id == 3
        assert reports == [("btcusdt", "before_resync")]
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_fan_in_measures_queue_drops(monkeypatch):
    reports = []

    async def fake_stream(symbol, *, on_reconnect):
        yield _book(1)
        yield _book(2)
        await asyncio.Future()

    monkeypatch.setattr(multi_stream, "stream_synchronized_depth", fake_stream)
    stream = multi_stream.stream_multi_depth(
        ["btcusdt"], max_queue=1, on_drop=lambda symbol, reason: reports.append((symbol, reason)),
    )
    try:
        first = await asyncio.wait_for(anext(stream), timeout=1)
        assert first.book.last_update_id == 2
        assert reports == [("btcusdt", "queue_overflow")]
    finally:
        await stream.aclose()


def test_watch_list_dedupes_and_adds_btc_for_alts():
    w = watch_list("solusdt", ("ethusdt", "solusdt", "bnbusdt"))
    assert w[0] == "solusdt"
    assert "ethusdt" in w
    assert "bnbusdt" in w
    assert "btcusdt" in w


def test_watch_list_btc_only_no_dup():
    w = watch_list("btcusdt", ())
    assert w == ["btcusdt"]



def test_watch_list_keeps_all_nine_fixed_paper_symbols():
    symbols = (
        "btcusdt", "ethusdt", "solusdt", "bnbusdt", "xrpusdt",
        "adausdt", "dogeusdt", "avaxusdt", "linkusdt",
    )
    assert watch_list("btcusdt", symbols) == list(symbols)
