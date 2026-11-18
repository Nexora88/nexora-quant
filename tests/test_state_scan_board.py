from datetime import datetime, timezone

from app.events import BookTicker
from app.state import RuntimeState


def test_snapshot_reports_all_watched_symbols_and_depth_freshness():
    state = RuntimeState()
    state.depth_watch = ["btcusdt", "ethusdt", "solusdt"]
    state.latest_book = BookTicker(
        symbol="btcusdt",
        bid=99.9,
        bid_qty=2.0,
        ask=100.1,
        ask_qty=1.5,
        received_at=datetime.now(timezone.utc),
    )
    state.side_books = {
        "ethusdt": {
            "bid": 1999.0,
            "ask": 2001.0,
            "bid_qty": 4.0,
            "ask_qty": 3.0,
            "updated_at": __import__("time").time(),
        }
    }
    state.router_board = [{"symbol": "ethusdt", "score": 0.7}]

    snapshot = state.snapshot()
    rows = {row["symbol"]: row for row in snapshot["scan_board"]}

    assert set(rows) == {"btcusdt", "ethusdt", "solusdt"}
    assert rows["btcusdt"]["status"] == "synchronized"
    assert rows["ethusdt"]["status"] == "synchronized"
    assert rows["solusdt"]["status"] == "awaiting"
    assert snapshot["router_board"][0]["symbol"] == "ethusdt"
    assert snapshot["depth_watch"] == state.depth_watch
