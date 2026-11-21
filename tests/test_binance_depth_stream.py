from app.binance_depth import _apply_depth_event
from app.depth_book import DepthBook


def make_book():
    book = DepthBook()
    book.load_snapshot(
        last_update_id=100,
        bids=[(99.0, 1.0)],
        asks=[(101.0, 1.0)],
    )
    return book


def test_stale_or_duplicate_depth_event_is_ignored_without_resync():
    book = make_book()
    stale = {"U": 95, "u": 100, "b": [["99.0", "2.0"]], "a": []}
    duplicate = {"U": 100, "u": 100, "b": [], "a": []}

    assert _apply_depth_event(book, stale) is True
    assert _apply_depth_event(book, duplicate) is True
    assert book.synchronized is True
    assert book.last_update_id == 100
    assert book.bids[99.0] == 1.0


def test_contiguous_depth_event_is_applied():
    book = make_book()
    event = {"U": 100, "u": 102, "b": [["99.0", "2.0"]], "a": []}

    assert _apply_depth_event(book, event) is True
    assert book.synchronized is True
    assert book.last_update_id == 102
    assert book.bids[99.0] == 2.0


def test_real_depth_sequence_gap_invalidates_book():
    book = make_book()
    gap = {"U": 103, "u": 104, "b": [], "a": []}

    assert _apply_depth_event(book, gap) is False
    assert book.synchronized is False
    assert book.last_update_id == 100
