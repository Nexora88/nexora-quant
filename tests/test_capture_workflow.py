"""Offline capture -> integrity check -> replay, plus broken data-source paths."""
import asyncio
from datetime import datetime, timezone
import json
import time
from types import SimpleNamespace

import pytest

from app.depth_book import DepthBook
from app.events import TradeTick
from app.market_history import MarketHistoryWriter, replay_market_history, verify_capture_archive
from scripts import capture_multi_symbol as capture


def capture_args(tmp_path):
    return SimpleNamespace(
        output_dir=tmp_path / "run", symbol=["btcusdt"], seconds=0.05, no_seed=True,
        min_depth_frames=2, max_depth_gap_seconds=1.0,
    )


@pytest.mark.parametrize("disconnect", [False, True])
def test_bounded_capture_preserves_coverage_and_detects_tampering(tmp_path, monkeypatch, disconnect):
    async def depth(symbol, *, on_reconnect):
        book = DepthBook(symbol=symbol)
        for update in range(3):
            book.load_snapshot(last_update_id=10 + update, bids=[(99.9, 5)], asks=[(100.1, 5)])
            yield book.publish(received_at_ns=time.time_ns(), received_monotonic_ns=time.monotonic_ns())
        if disconnect:
            on_reconnect(symbol, ConnectionError("interruption"))
        await asyncio.Future()

    async def events(symbol, *, on_reconnect):
        yield TradeTick(symbol, 100.0, 0.5, False, datetime.now(timezone.utc))
        await asyncio.Future()

    monkeypatch.setattr(capture, "stream_synchronized_depth", depth)
    monkeypatch.setattr(capture, "stream_events", events)
    args = capture_args(tmp_path)
    assert asyncio.run(capture._capture_bounded(args)) == (2 if disconnect else 0)
    archive = args.output_dir / "btcusdt.jsonl.gz"
    manifest = args.output_dir / "manifest.json"
    contents = json.loads(manifest.read_text())
    assert contents["captures"][0]["events"] == {"depth": 3, "trade": 1, "kline": 0}
    rows = list(replay_market_history(archive))
    assert len(rows) == 4
    assert [row["payload"]["update_id"] for row in rows if row["event_type"] == "depth"] == [10, 11, 12]
    if disconnect:
        with pytest.raises(ValueError, match="coverage"):
            verify_capture_archive(archive, manifest)
    else:
        assert verify_capture_archive(archive, manifest) == contents["captures"][0]["sha256"]
        with archive.open("ab") as stream:
            stream.write(b"changed")
        with pytest.raises(ValueError, match="hash"):
            verify_capture_archive(archive, manifest)
    with pytest.raises(FileExistsError):
        asyncio.run(capture._capture_bounded(args))


def test_writer_never_retries_a_potential_partial_batch(tmp_path, monkeypatch):
    import app.market_history as mh

    def failed_write(*args, **kwargs):
        raise OSError("disk full")

    writer = MarketHistoryWriter(tmp_path / "market.jsonl.gz", max_pending=2)
    writer.append(timestamp_ns=1, event_type="trade", payload={})
    with monkeypatch.context() as patch:
        patch.setattr(mh.gzip, "open", failed_write)
        with pytest.raises(OSError, match="disk full"):
            writer.flush()
    assert writer.stats()["pending"] == 1
    with pytest.raises(RuntimeError, match="incomplete"):
        writer.flush()
    assert not writer.path.exists()
