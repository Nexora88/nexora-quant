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
