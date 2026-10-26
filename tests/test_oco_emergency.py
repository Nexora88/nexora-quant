"""OCO install retries + emergency flatten contract (mocked client)."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from app.live import LiveExecutor
from app.live_hardening import harden_live_executor
from app.io_queue import AsyncIoQueue

# Patch LiveExecutor methods after import (idempotent).
harden_live_executor()


class _Boom(Exception):
    pass


def test_ensure_protective_oco_retries_then_succeeds():
    client = MagicMock()
    client.free_balance.return_value = 0.01
    client.exchange_info_symbol.return_value = {
        "filters": [
            {"filterType": "LOT_SIZE", "stepSize": "0.00001"},
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
        ]
    }
    calls = {"n": 0}

    def place_oco(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Boom("HTTP 502")
        return {"orderListId": 42}

    client.place_oco_order.side_effect = place_oco
    ex = LiveExecutor(client, symbol="btcusdt", fee_rate=0.001)
    ex.base_quantity = 0.01
    ex.average_entry_price = 100.0
    ok = ex.ensure_protective_oco(
        current_price=100.0, take_profit_pct=1.0, stop_loss_pct=0.5, retries=3, retry_delay_s=0.0,
    )
    assert ok is True
    assert ex.protective_order_list_id == 42
    assert calls["n"] == 3


def test_ensure_protective_oco_fails_after_retries():
    client = MagicMock()
    client.free_balance.return_value = 0.01
    client.exchange_info_symbol.return_value = {
        "filters": [
            {"filterType": "LOT_SIZE", "stepSize": "0.00001"},
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
        ]
    }
    client.place_oco_order.side_effect = _Boom("HTTP 502")
    ex = LiveExecutor(client, symbol="btcusdt", fee_rate=0.001)
    ex.base_quantity = 0.01
    ex.average_entry_price = 100.0
    ok = ex.ensure_protective_oco(
        current_price=100.0, take_profit_pct=1.0, stop_loss_pct=0.5, retries=2, retry_delay_s=0.0,
    )
    assert ok is False


def test_install_protection_or_flatten_triggers_emergency():
    client = MagicMock()
    client.free_balance.return_value = 0.01
    client.exchange_info_symbol.return_value = {
        "filters": [
            {"filterType": "LOT_SIZE", "stepSize": "0.00001"},
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
        ]
    }
    client.place_oco_order.side_effect = _Boom("HTTP 502")
    client.place_order.return_value = {
        "orderId": 99,
        "executedQty": "0.01",
        "cummulativeQuoteQty": "1.0",
        "status": "FILLED",
        "fills": [{"price": "100.0", "qty": "0.01", "commission": "0", "commissionAsset": "USDT"}],
    }
    ex = LiveExecutor(client, symbol="btcusdt", fee_rate=0.001)
    ex.base_quantity = 0.01
    ex.average_entry_price = 100.0
    ex.quote_balance = 0.0
    ok = ex.install_protection_or_flatten(
        current_price=100.0, take_profit_pct=1.0, stop_loss_pct=0.5, mark_price=100.0,
    )
    assert ok is False
    assert ex.emergency is True
    assert ex.emergency_reason == "oco_install_failed"


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
        q.enqueue_state("k", {"a": 3})  # may drop oldest state
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
