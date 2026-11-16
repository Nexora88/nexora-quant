from concurrent.futures import ThreadPoolExecutor

from app.storage import PaperStore


def test_shared_store_serializes_concurrent_idempotent_writes(tmp_path):
    store = PaperStore(tmp_path / "paper.sqlite3")
    try:
        def write(index):
            store.save_state("paper:btcusdt", {"counter": index})
            return store.append_trade({"side": "buy", "index": index}, event_key="same-event")

        with ThreadPoolExecutor(max_workers=8) as pool:
            inserted = list(pool.map(write, range(32)))

        assert sum(inserted) == 1
        assert len(store.list_trades(limit=100)) == 1
        assert store.load_state("paper:btcusdt")["counter"] in range(32)
    finally:
        store.close()

def test_failed_flush_retains_state_and_trade_batch_for_retry(tmp_path):
    import sqlite3

    store = PaperStore(tmp_path / "retry.sqlite3", flush_interval_s=60)
    try:
        store._db.execute(
            """CREATE TRIGGER reject_paper_state BEFORE INSERT ON paper_state
               BEGIN SELECT RAISE(ABORT, 'simulated disk constraint failure'); END"""
        )
        store.save_state("paper:btcusdt", {"cash": 91.0})
        assert store.append_trade({"side": "buy", "qty": 0.1}, event_key="retry-event")

        try:
            store.flush()
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("failed transaction must be reported")

        assert "paper:btcusdt" in store._pending_states
        assert "retry-event" in store._pending_trade_keys

        store._db.execute("DROP TRIGGER reject_paper_state")
        store.flush()
        assert store.load_state("paper:btcusdt") == {"cash": 91.0}
        assert len(store.list_trades()) == 1
        assert not store._pending_states
        assert not store._pending_trades
    finally:
        store.close()

def test_paper_session_heartbeat_and_finalization_are_durable(tmp_path):
    path = tmp_path / "sessions.sqlite3"
    with PaperStore(path, async_writes=False) as store:
        store.start_session("session-1", "paper")
        store.heartbeat_session(
            "session-1", ticks=1200, reconnects=2,
            trade_count=24, realized_pnl_usdt=1.25,
        )
        active = store.latest_session("paper")
        assert active is not None
        assert active["ticks"] == 1200
        assert active["reconnects"] == 2
        assert active["trade_count"] == 24
        assert active["ended_at"] is None
        store.end_session(
            "session-1", ticks=1300, reconnects=2,
            trade_count=26, realized_pnl_usdt=1.50,
        )
        ended = store.latest_session("paper")
        assert ended is not None
        assert ended["ended_at"] is not None
        assert ended["ticks"] == 1300
