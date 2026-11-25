"""Unit tests for offline OCO fill recovery; no network or real orders."""
import pytest

from app.binance_rest import OrderResult
from app.live import LiveExecutor
from app.storage import PaperStore


class FakeClient:
    testnet = True

    def __init__(self, *, fills=None, status="ALL_DONE"):
        self.fills = fills if fills is not None else [{
            "id": 7, "orderId": 41, "time": 1000, "isBuyer": False,
            "qty": "1.0", "price": "110.0", "quoteQty": "110.0",
            "commission": "0.11", "commissionAsset": "USDT",
        }]
        self.status = status

    def get_order_list(self, list_id):
        return {
            "symbol": "BTCUSDT", "orderListId": list_id,
            "listStatusType": self.status,
            "orders": [{"orderId": 41}, {"orderId": 42}],
        }

    def exchange_info_symbol(self, symbol):
        return {"filters": [{"filterType": "LOT_SIZE", "stepSize": "0.00001"}]}

    def get_order(self, symbol, order_id):
        qty = sum(float(x["qty"]) for x in self.fills) if order_id == 41 else 0.0
        return OrderResult(
            order_id=order_id, client_order_id="oco-child", symbol=symbol,
            side="SELL", status="FILLED" if qty else "CANCELED", price=110.0,
            orig_qty=1.0, executed_qty=qty, cummulative_quote_qty=qty * 110.0,
            fills=[], raw={},
        )

    def order_trades(self, symbol, order_id):
        return list(self.fills)


def make_executor(client):
    executor = LiveExecutor(
        client, symbol="BTCUSDT", fee_rate=0.001,
        base_asset="BTC", quote_asset="USDT",
    )
    executor.base_quantity = 1.0
    executor.average_entry_price = 100.0
    executor.cash_usdt = 0.0
    executor.protective_order_list_id = 9
    executor.order_lists_reconciled = True
    return executor


def test_completed_oco_fill_is_recovered_and_repeat_is_idempotent():
    executor = make_executor(FakeClient())
    assert executor.reconcile_protective_oco() is True
    assert executor.base_quantity == 0.0
    assert round(executor.cash_usdt, 2) == 109.89
    assert round(executor.realized_pnl_usdt, 2) == 9.89
    assert executor.processed_exchange_trade_ids == {"7"}
    assert len(executor.trades) == 1
    snapshot = executor.snapshot()
    restored = make_executor(FakeClient())
    restored.restore(snapshot)
    restored.protective_order_list_id = 9
    assert restored.reconcile_protective_oco() is True
    assert len(restored.trades) == 1
    assert round(restored.realized_pnl_usdt, 2) == 9.89


def test_unpriced_commission_fails_closed_without_partial_accounting():
    client = FakeClient(fills=[{
        "id": 8, "orderId": 41, "time": 1000, "isBuyer": False,
        "qty": "1.0", "price": "110.0", "quoteQty": "110.0",
        "commission": "0.01", "commissionAsset": "BNB",
    }])
    executor = make_executor(client)
    assert executor.reconcile_protective_oco() is False
    assert executor.protective_order_list_id == 9
    assert executor.order_lists_reconciled is False
    assert executor.base_quantity == 1.0
    assert executor.cash_usdt == 0.0
    assert executor.trades == []


def test_active_oco_is_not_misbooked_as_a_fill():
    executor = make_executor(FakeClient(status="EXECUTING"))
    assert executor.reconcile_protective_oco() is True
    assert executor.base_quantity == 1.0
    assert executor.trades == []
    assert executor.protective_order_list_id == 9


def test_cancel_and_late_fill_are_atomic_even_if_checkpoint_fails(tmp_path, monkeypatch):
    class LateFill(FakeClient):
        def cancel_order_list(self, **params):
            assert params["order_list_id"] == 9
            raise TimeoutError("late fill happened before cancellation response")

    client = LateFill()
    path = str(tmp_path / "oco.sqlite")
    key = "live:btcusdt"
    with PaperStore(path, async_writes=False) as store:
        ex = make_executor(client)
        ex.attach_order_journal(store, key)
        store.checkpoint_live_account(key, ex.snapshot(), [])
        with monkeypatch.context() as patch:
            def broken_write(*args, **kwargs):
                raise OSError("SQLite checkpoint unavailable")

            patch.setattr(store, "checkpoint_live_account", broken_write)
            assert not ex.cancel_protective_oco()
            assert ex.base_quantity == 1.0
            assert ex.protective_order_list_id == 9
            assert not ex.order_lists_reconciled
            assert ex.trades == []
            assert store.list_trades() == []
            with pytest.raises(RuntimeError, match="Protective order"):
                ex.sell_all(price=110, reason="must_not_compete")

    with PaperStore(path, async_writes=False) as store:
        ex = make_executor(client)
        ex.restore(store.load_state(key)["account"])
        ex.attach_order_journal(store, key)
        assert ex.cancel_protective_oco()
        assert ex.reconcile_protective_oco()
        assert ex.base_quantity == 0.0
        assert ex.protective_order_list_id is None
        assert store.load_state(key)["account"]["realized_pnl_usdt"] == pytest.approx(9.89)
        assert len(store.list_trades()) == len(ex.trades) == 1


def test_duplicate_child_ids_do_not_clear_protection():
    class DuplicateChild(FakeClient):
        def get_order_list(self, list_id):
            return {**super().get_order_list(list_id), "orders": [{"orderId": 41}, {"orderId": 41}]}

    ex = make_executor(DuplicateChild())
    assert not ex.reconcile_protective_oco()
    assert ex.base_quantity == 1.0
    assert ex.protective_order_list_id == 9
    assert not ex.trades


def test_live_snapshot_persists_oco_client_id_for_restart_reconciliation():
    executor = make_executor(FakeClient())
    executor.protective_order_client_id = "nqoco-order-123"
    restored = make_executor(FakeClient())
    restored.restore(executor.snapshot())
    assert restored.protective_order_client_id == "nqoco-order-123"


def test_terminal_cancelled_oco_rotates_id_and_reprotects_remaining_quantity():
    class RotatingClient:
        testnet = True

        def __init__(self):
            self.placed = None

        def get_order_list_by_client_id(self, symbol, client_order_id):
            return {
                "orderListId": 12, "symbol": symbol, "listStatusType": "ALL_DONE",
                "listClientOrderId": client_order_id,
            }

        def get_order_list(self, list_id):
            return {
                "symbol": "BTCUSDT", "orderListId": list_id,
                "listStatusType": "ALL_DONE",
                "orderReports": [{"orderId": 101}, {"orderId": 102}],
            }

        def get_order(self, symbol, order_id):
            return OrderResult(
                order_id=order_id, client_order_id="old-child", symbol=symbol,
                side="SELL", status="CANCELED", price=0, orig_qty=0.5,
                executed_qty=0, cummulative_quote_qty=0, fills=[], raw={},
            )

        def order_list_trades(self, symbol, order_id):
            return []

        def free_balance(self, asset):
            return 0.5

        def exchange_info_symbol(self, symbol):
            return {"filters": [
                {"filterType": "LOT_SIZE", "stepSize": "0.00001"},
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
            ]}

        def place_oco_order(self, **kwargs):
            self.placed = kwargs
            return {
                "orderListId": 13, "listStatusType": "EXEC_STARTED",
                "listClientOrderId": kwargs["client_order_id"], "symbol": kwargs["symbol"],
            }

    client = RotatingClient()
    executor = LiveExecutor(client, symbol="BTCUSDT", fee_rate=0.001)
    executor.base_quantity = 0.5
    executor.average_entry_price = 100
    executor.protective_order_client_id = "nqoco-old-position"
    assert executor.ensure_protective_oco(
        current_price=100, take_profit_pct=1.0, stop_loss_pct=0.5,
        retries=1, retry_delay_s=0,
    ) is True
    assert executor.protective_order_list_id == 13
    assert client.placed["client_order_id"] != "nqoco-old-position"
    assert client.placed["quantity"] == pytest.approx(0.5)
