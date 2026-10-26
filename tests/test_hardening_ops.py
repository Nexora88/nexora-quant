"""WAL concurrency, history backpressure, day-rollover contract."""
from __future__ import annotations

import tempfile
from pathlib import Path

from app.market_history import MarketHistoryWriter, replay_market_history
from app.risk import RiskManager
from app.sqlite_util import connect_sqlite
from app.storage import PaperStore


def test_sqlite_wal_mode_forced():
    with tempfile.TemporaryDirectory() as td:
        path = str(Path(td) / "t.sqlite3")
        db = connect_sqlite(path)
        mode = db.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() == "wal"
        db.close()


def test_paper_store_wal():
    with tempfile.TemporaryDirectory() as td:
        path = str(Path(td) / "paper.sqlite3")
        store = PaperStore(path, async_writes=False)
        mode = store._db.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() == "wal"
        store.close()


def test_history_drop_oldest_backpressure(tmp_path: Path):
    path = tmp_path / "h.jsonl.gz"
    w = MarketHistoryWriter(path, max_pending=5)
    for i in range(20):
        w.append(timestamp_ns=i, event_type="depth", payload={"i": i})
    w.flush()
    st = w.stats()
    assert st["dropped"] >= 10
    assert st["pending"] == 0
    rows = list(replay_market_history(path))
    assert len(rows) >= 1
    assert rows[0]["timestamp_ns"] <= rows[-1]["timestamp_ns"]


def test_history_write_through_no_drop(tmp_path: Path):
    path = tmp_path / "h2.jsonl.gz"
    w = MarketHistoryWriter(path, max_pending=0)
    for i in range(5):
        w.append(timestamp_ns=i, event_type="depth", payload={"i": i})
    assert w.stats()["dropped"] == 0
    assert list(replay_market_history(path))[-1]["payload"]["i"] == 4


def test_day_rollover_resets_pnl_only():
    risk = RiskManager(
        max_order_size_usdt=10,
        max_daily_loss_usdt=5,
        max_consecutive_losses=5,
        max_spread_bps=20,
        max_data_age_seconds=8,
    )
    risk.rollover_day("2026-10-25")
    risk.realized_pnl_today = -3.0
    risk.consecutive_losses = 2
    assert risk.rollover_day("2026-10-26") is True
    assert risk.realized_pnl_today == 0.0
    assert risk.consecutive_losses == 2
    assert risk.rollover_day("2026-10-26") is False
