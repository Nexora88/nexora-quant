from datetime import datetime, timezone
import time

from app.events import BookTicker
from app.state import RuntimeState


def test_snapshot_reports_all_watched_symbols_and_depth_freshness():
    state = RuntimeState()
    state.depth_watch = ["btcusdt", "ethusdt", "solusdt"]
    state.update_book(BookTicker(
        symbol="btcusdt",
        bid=99.9,
        bid_qty=2.0,
        ask=100.1,
        ask_qty=1.5,
        received_at=datetime.now(timezone.utc),
    ))
    state.side_books = {
        "ethusdt": {
            "bid": 1999.0,
            "ask": 2001.0,
            "bid_qty": 4.0,
            "ask_qty": 3.0,
            "updated_at": time.time(),
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


def test_snapshot_exposes_consolidated_risk_book():
    from app.risk import RiskManager
    from app.state import RuntimeState

    state = RuntimeState()
    state.risk_manager = RiskManager(
        max_order_size_usdt=25, max_daily_loss_usdt=2,
        max_consecutive_losses=4, max_spread_bps=22,
        max_data_age_seconds=8, max_daily_fee_usdt=0.75,
    )
    state.risk_manager.record_fee(0.20)
    state.session_realized_pnl_usdt = -0.15
    state.peak_equity = 100.0
    risk_book = state.snapshot()["risk_book"]
    assert risk_book["daily_fee_usdt"] == 0.20
    assert risk_book["daily_fee_remaining_usdt"] == 0.55
    assert risk_book["session_pnl_usdt"] == -0.15
    assert risk_book["daily_fee_halt"] is False
