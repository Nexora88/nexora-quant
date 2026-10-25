from app.binance_rest import OrderResult
from app.live import LiveExecutor


class FakeClient:
    testnet = True

    def __init__(self, *, uncertain=False):
        self.uncertain = uncertain
        self.lookup_count = 0
        self.place_count = 0
        self.last_client_id = None
        self.oco = None

    def get_order_by_client_id(self, symbol, client_order_id):
        self.lookup_count += 1
        if self.uncertain and self.lookup_count >= 2:
            raise RuntimeError("temporary lookup outage")
        if self.lookup_count == 1 or not self.uncertain:
            raise RuntimeError("Binance API error 400: -2013 Order does not exist.")
        return self.result(client_order_id)

    def place_market_order(self, *, symbol, side, quantity=None, quote_order_qty=None, client_order_id=None):
        self.place_count += 1
        self.last_client_id = client_order_id
        if self.uncertain:
            raise TimeoutError("response lost after request")
        return self.result(client_order_id, side=side)

    def result(self, client_order_id, side="BUY"):
        return OrderResult(
            order_id=123, client_order_id=client_order_id, symbol="BTCUSDT",
            side=side, status="FILLED", price=100, orig_qty=0.1,
            executed_qty=0.1, cummulative_quote_qty=10, fills=[],
            raw={"orderId": 123},
        )

    def exchange_info_symbol(self, symbol):
        return {"filters": [
            {"filterType": "LOT_SIZE", "stepSize": "0.001"},
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
        ]}

    def free_balance(self, asset):
        return 0.1

    def place_oco_order(self, **kwargs):
        self.oco = kwargs
        return {"orderListId": 77, "symbol": kwargs["symbol"], "listStatusType": "EXECUTING"}

    def account(self):
        return {"balances": [
            {"asset": "USDT", "free": "100", "locked": "0"},
            {"asset": "BTC", "free": "0.1", "locked": "0"},
        ]}

    def open_orders(self, symbol):
        return []

    def open_order_lists(self):
        return []


def test_unknown_order_outcome_blocks_further_submissions():
    client = FakeClient(uncertain=True)
    executor = LiveExecutor(client, symbol="BTCUSDT", fee_rate=0.001)
    try:
        executor._place_market_order_once(side="BUY", reason="unit-test", quote_order_qty=10)
    except Exception:
        pass
    else:
        raise AssertionError("timed-out order should not be treated as confirmed")
    assert executor.order_state_uncertain
    assert executor.unresolved_client_order_id
    try:
        executor._place_market_order_once(side="BUY", reason="retry", quote_order_qty=10)
    except RuntimeError as exc:
        assert "uncertain" in str(exc)
    else:
        raise AssertionError("new order must be blocked while outcome is uncertain")
    assert client.place_count == 1


def test_exchange_hosted_oco_is_created_with_rounded_prices():
    client = FakeClient()
    executor = LiveExecutor(client, symbol="BTCUSDT", fee_rate=0.001)
    executor.base_quantity = 0.1
    executor.average_entry_price = 100
    assert executor.ensure_protective_oco(
        current_price=100, take_profit_pct=1.0, stop_loss_pct=0.5,
    )
    assert client.oco["side"] == "SELL"
    assert client.oco["take_profit_price"] == 101.0
    assert client.oco["stop_price"] == 99.5
    assert client.oco["stop_limit_price"] < client.oco["stop_price"]
    assert executor.protective_order_list_id == 77


def test_invalid_oco_prices_fail_closed():
    client = FakeClient()
    executor = LiveExecutor(client, symbol="BTCUSDT", fee_rate=0.001)
    executor.base_quantity = 0.1
    executor.average_entry_price = 100
    assert not executor.ensure_protective_oco(
        current_price=102, take_profit_pct=1.0, stop_loss_pct=0.5,
    )
