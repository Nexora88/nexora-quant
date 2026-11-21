import pytest

from app.binance_rest import BinanceRestClient


def test_ticker_price_uses_public_symbol_endpoint(monkeypatch):
    client = BinanceRestClient(api_key="key", api_secret="secret")
    calls = []

    def fake_request(method, path, params=None, *, signed=False):
        calls.append((method, path, params, signed))
        return {"symbol": "BNBUSDT", "price": "612.34"}

    monkeypatch.setattr(client, "_request", fake_request)
    assert client.ticker_price("bnbusdt") == pytest.approx(612.34)
    assert calls == [("GET", "/api/v3/ticker/price", {"symbol": "BNBUSDT"}, False)]


def test_ticker_price_rejects_invalid_symbol_and_response(monkeypatch):
    client = BinanceRestClient(api_key="key", api_secret="secret")
    with pytest.raises(ValueError):
        client.ticker_price("BNB/USDT")
    monkeypatch.setattr(client, "_request", lambda *a, **k: {"price": "0"})
    with pytest.raises(RuntimeError):
        client.ticker_price("BNBUSDT")


def test_get_order_list_by_client_id_uses_exchange_idempotency_key(monkeypatch):
    client = BinanceRestClient(api_key="key", api_secret="secret", testnet=True)
    calls = []

    def fake_request(method, path, params=None, *, signed=False):
        calls.append((method, path, params, signed))
        return {"orderListId": 123, "listClientOrderId": "nqocoabc", "listStatusType": "EXECUTING"}

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.get_order_list_by_client_id("btcusdt", "nqocoabc")
    assert result["orderListId"] == 123
    assert calls == [("GET", "/api/v3/orderList", {
        "symbol": "BTCUSDT", "origClientOrderId": "nqocoabc",
    }, True)]


def test_oco_market_stop_omits_stop_limit_fields(monkeypatch):
    client = BinanceRestClient(api_key="key", api_secret="secret", testnet=True)
    calls = []
    monkeypatch.setattr(client, "_request", lambda method, path, params=None, *, signed=False: calls.append(params) or {"orderListId": 1})
    client.place_oco_order(
        symbol="BTCUSDT", side="SELL", quantity=0.01,
        take_profit_price=110, stop_price=90, stop_limit_price=89,
        client_order_id="nqoco1", stop_loss_market=True,
    )
    params = calls[0]
    assert params["belowType"] == "STOP_LOSS"
    assert params["belowStopPrice"] == "90"
    assert "belowPrice" not in params and "belowTimeInForce" not in params



def test_rest_helpers_cover_live_startup_and_testnet_workflow(monkeypatch):
    client = BinanceRestClient(api_key="key", api_secret="secret", testnet=True)
    calls = []

    def fake_request(method, path, params=None, *, signed=False):
        calls.append((method, path, params, signed))
        if path == "/api/v3/ping":
            return {}
        if path == "/api/v3/exchangeInfo":
            return {"symbols": [{"symbol": "BTCUSDT", "baseAsset": "BTC", "filters": []}]}
        if path == "/api/v3/account":
            return {"balances": [{"asset": "USDT", "free": "12.5", "locked": "1"}]}
        if path == "/api/v3/openOrders":
            return [{"orderId": 7, "symbol": "BTCUSDT", "status": "NEW"}]
        if path == "/api/v3/order":
            return {
                "orderId": 7, "clientOrderId": "nq-7", "symbol": "BTCUSDT",
                "side": "BUY", "status": "FILLED", "executedQty": "1",
                "cummulativeQuoteQty": "10", "fills": [],
            }
        raise AssertionError(path)

    monkeypatch.setattr(client, "_request", fake_request)
    assert client.ping() is True
    assert client.exchange_info_symbol("btcusdt")["baseAsset"] == "BTC"
    assert client.free_balance("usdt") == pytest.approx(12.5)
    assert client.open_orders("btcusdt")[0]["orderId"] == 7
    assert client.get_order_by_client_id("btcusdt", "nq-7").order_id == 7
    assert calls[0] == ("GET", "/api/v3/ping", None, False)
    assert calls[1] == ("GET", "/api/v3/exchangeInfo", {"symbol": "BTCUSDT"}, False)
    assert calls[3] == ("GET", "/api/v3/openOrders", {"symbol": "BTCUSDT"}, True)


def test_all_orders_and_my_trades_paginate_without_skipping_ids(monkeypatch):
    client = BinanceRestClient(api_key="key", api_secret="secret", testnet=True)
    calls = []

    def fake_request(method, path, params=None, *, signed=False):
        calls.append((path, dict(params or {})))
        if path == "/api/v3/allOrders":
            if "orderId" not in params:
                return [{"orderId": 10}, {"orderId": 11}]
            return [{"orderId": 12}]
        if path == "/api/v3/myTrades":
            if "fromId" not in params:
                return [{"id": 20}, {"id": 21}]
            return [{"id": 22}]
        raise AssertionError(path)

    monkeypatch.setattr(client, "_request", fake_request)
    orders = client.all_orders("BTCUSDT", limit=2)
    trades = client.all_my_trades("BTCUSDT", limit=2)
    assert [item["orderId"] for item in orders] == [10, 11, 12]
    assert [item["id"] for item in trades] == [20, 21, 22]
    assert calls[1] == ("/api/v3/allOrders", {"symbol": "BTCUSDT", "limit": 2, "orderId": 12})
    assert calls[3] == ("/api/v3/myTrades", {"symbol": "BTCUSDT", "limit": 2, "fromId": 22})


def test_all_order_lists_plural_alias(monkeypatch):
    client = BinanceRestClient(api_key="key", api_secret="secret", testnet=True)
    monkeypatch.setattr(client, "all_order_list", lambda **kwargs: [{"orderListId": 1}])
    assert client.all_order_lists(limit=25) == [{"orderListId": 1}]
