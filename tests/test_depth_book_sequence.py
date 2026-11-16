from __future__ import annotations

import math

import pytest

from app.depth_book import DepthBook


def make_book() -> DepthBook:
    book = DepthBook(symbol="btcusdt")
    book.load_snapshot(last_update_id=100, bids=[(99, 2)], asks=[(101, 3)])
    return book


def test_contiguous_update_requires_matching_previous_final_id():
    book = make_book()
    assert book.apply_diff(
        first_update_id=100, final_update_id=102, previous_final_update_id=100,
        bids=[(100, 1)], asks=[],
    )
    assert book.last_update_id == 102
    assert book.best_bid == (100.0, 1.0)


def test_overlapping_update_range_with_wrong_previous_id_invalidates_book():
    book = make_book()
    # U is not beyond lastUpdateId + 1, so the old U/u-only check accepted this.
    assert not book.apply_diff(
        first_update_id=101, final_update_id=103, previous_final_update_id=99,
        bids=[(100, 1)], asks=[],
    )
    assert not book.synchronized
    assert book.last_update_id == 100
    assert book.best_bid == (99.0, 2.0)


def test_update_gap_invalidates_book():
    book = make_book()
    assert not book.apply_diff(
        first_update_id=102, final_update_id=103, previous_final_update_id=100,
        bids=[], asks=[],
    )
    assert not book.synchronized


def test_malformed_ask_does_not_partially_apply_bid():
    book = make_book()
    with pytest.raises(ValueError):
        book.apply_diff(
            first_update_id=101, final_update_id=101,
            bids=[(100, 1)], asks=[(math.nan, 2)],
        )
    assert not book.synchronized
    assert book.last_update_id == 100
    assert book.best_bid == (99.0, 2.0)


@pytest.mark.parametrize("level", [(0, 1), (-1, 1), (100, -1), (math.inf, 1), (100, math.nan)])
def test_snapshot_rejects_invalid_levels(level):
    book = DepthBook()
    with pytest.raises(ValueError):
        book.load_snapshot(last_update_id=1, bids=[level], asks=[])
    assert not book.synchronized
