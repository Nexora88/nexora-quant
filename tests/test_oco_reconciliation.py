"""Unit tests for offline OCO fill recovery; no network or real orders."""
from app.binance_rest import OrderResult
from app.live import LiveExecutor


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
            "orderReports": [{"orderId": 41}],
        }

    def get_order(self, symbol, order_id):
        qty = sum(float(x["qty"]) for x in self.fills)
        return OrderResult(
            order_id=order_id, client_order_id="oco-child", symbol=symbol,
            side="SELL", status="FILLED", price=110.0, orig_qty=qty,
            executed_qty=qty, cummulative_quote_qty=qty * 110.0,
            fills=[], raw={},
        )

    def order_list_trades(self, symbol, order_id):
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
    assert executor.order_state_uncertain is True
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
