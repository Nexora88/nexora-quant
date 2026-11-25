import time
from unittest.mock import Mock

import pytest

from app import depth_book
from app.depth_book import DepthBook


def make_book():
    book = DepthBook(symbol="btcusdt")
    book.load_snapshot(last_update_id=1, bids=[(99, 2)], asks=[(101, 2)])
    return book


def test_age_includes_exchange_delay_and_queue_delay(monkeypatch):
    monkeypatch.setattr(depth_book.time, "monotonic_ns", lambda: 5_000_000_000)
    snapshot = make_book().publish(
        received_at_ns=20_000_000_000, received_monotonic_ns=2_000_000_000,
        exchange_at_ms=18_000,
    )
    assert snapshot.age_seconds() == 5


def test_future_exchange_clock_fails_closed(monkeypatch):
    monkeypatch.setattr(depth_book.time, "monotonic_ns", lambda: 5_000_000_000)
    snapshot = make_book().publish(
        received_at_ns=20_000_000_000, received_monotonic_ns=4_000_000_000,
        exchange_at_ms=26_000,
    )
    assert snapshot.age_seconds() == float("inf")


@pytest.mark.asyncio
async def test_stale_depth_does_not_reach_analysis_or_storage(monkeypatch):
    from app import engine_tick_body

    analysis = Mock(side_effect=AssertionError("stale data must not reach analysis"))
    monkeypatch.setattr(engine_tick_body, "analyze_market", analysis)
    snapshot = make_book().publish(
        received_at_ns=time.time_ns(), received_monotonic_ns=time.monotonic_ns() - 100_000_000_000,
    )
    history = Mock()
    result = await engine_tick_body.handle_tick(snapshot, Mock(), history, Mock(), "paper", "test", Mock(), 0, 5)
    assert result == (0, 5)
    assert not history.mock_calls
    assert not analysis.mock_calls
