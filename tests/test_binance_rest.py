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
