"""LIMIT_MAKER helper exists on REST client (no network)."""
from app.binance_rest import BinanceRestClient


def test_place_limit_order_method_exists() -> None:
    assert hasattr(BinanceRestClient, "place_limit_order")
    assert hasattr(BinanceRestClient, "place_market_order")
