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
