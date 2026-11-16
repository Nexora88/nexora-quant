"""Paper IO queue regression tests; no live OCO or exchange orders."""
import asyncio

from app.io_queue import AsyncIoQueue


def test_io_queue_stats_and_drop_state():
    class Stub:
        def save_state(self, key, state):
            pass

        def append_trade(self, trade, event_key=None):
            pass

    async def run():
        q = AsyncIoQueue(Stub(), maxsize=2)
        q.start()
        q.enqueue_state("k", {"a": 1})
        q.enqueue_state("k", {"a": 2})
        q.enqueue_state("k", {"a": 3})
        st = q.stats()
        assert "queue_depth" in st
        assert st["queue_max"] == 2
        assert "dropped_state" in st
        assert "queue_peak" in st
        await q.stop()

    asyncio.run(run())


def test_io_queue_trade_sync_fallback_when_full():
    writes = {"trade": 0}

    class Stub:
        def save_state(self, key, state):
            pass

        def append_trade(self, trade, event_key=None):
            writes["trade"] += 1

    async def run():
        q = AsyncIoQueue(Stub(), maxsize=1)
        q.start()
        q.enqueue_state("s", {"x": 1})
        q.enqueue_trade({"side": "buy", "price": 1.0}, event_key="e1")
        await asyncio.sleep(0.05)
        await q.stop()
        assert writes["trade"] >= 1 or q.stats()["writes"] >= 1

    asyncio.run(run())
