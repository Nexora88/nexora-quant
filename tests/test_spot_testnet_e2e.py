"""Opt-in Binance Spot Testnet E2E smoke test.

This test submits orders only to the Spot Testnet. It is skipped unless explicitly
enabled and refuses to run if the client is not pointed at the testnet host.
"""
import os
from decimal import Decimal, ROUND_DOWN, ROUND_UP

import pytest

from app.binance_rest import BinanceRestClient


pytestmark = pytest.mark.skipif(
    os.getenv("NEXORA_RUN_SPOT_TESTNET_E2E") != "1",
    reason="set NEXORA_RUN_SPOT_TESTNET_E2E=1 to submit small Spot Testnet orders",
)


def _round_step(value: float, step: str, rounding=ROUND_DOWN) -> float:
    v, s = Decimal(str(value)), Decimal(step)
    return float((v / s).to_integral_value(rounding=rounding) * s)


def test_spot_testnet_market_oco_cancel_and_recovery_flow():
    key = os.getenv("BINANCE_API_KEY", "")
    secret = os.getenv("BINANCE_API_SECRET", "")
    symbol = os.getenv("NEXORA_TESTNET_SYMBOL", "BTCUSDT").upper()
    quote_amount = float(os.getenv("NEXORA_TESTNET_ORDER_QUOTE_USDT", "15"))
    if not key or not secret:
        pytest.fail("Testnet E2E requires BINANCE_API_KEY and BINANCE_API_SECRET")
    if quote_amount < 10:
        pytest.fail("NEXORA_TESTNET_ORDER_QUOTE_USDT must be at least 10 USDT")

    client = BinanceRestClient(api_key=key, api_secret=secret, testnet=True)
    assert client.testnet is True
    assert client.base == "https://testnet.binance.vision"
    client.ping()
    client.account()
    info = client.exchange_info_symbol(symbol)
    filters = {item["filterType"]: item for item in info.get("filters", [])}
    lot = filters.get("LOT_SIZE") or filters.get("MARKET_LOT_SIZE")
    price_filter = filters.get("PRICE_FILTER")
    assert lot and price_filter, "symbol did not expose required lot/price filters"

    buy = client.place_market_order(
        symbol=symbol, side="BUY", quote_order_qty=quote_amount,
        client_order_id=f"nq-e2e-buy-{os.getpid()}",
    )
    assert buy.order_id > 0 and buy.status in {"FILLED", "PARTIALLY_FILLED"}
    if buy.executed_qty <= 0:
        pytest.fail("Testnet market buy did not execute")

    base_asset = str(info.get("baseAsset", "BTC")).upper()
    quote_asset = str(info.get("quoteAsset", "USDT")).upper()
    base_fee = sum(
        float(fill.get("commission", 0))
        for fill in buy.fills
        if str(fill.get("commissionAsset", "")).upper() == base_asset
    )
    sellable = _round_step(
        buy.executed_qty - base_fee, lot["stepSize"], ROUND_DOWN,
    )
    assert sellable > 0
    current = client.ticker_price(symbol)
    tick = price_filter["tickSize"]
    tp = _round_step(current * 1.02, tick, ROUND_UP)
    stop = _round_step(current * 0.98, tick, ROUND_DOWN)
    stop_limit = _round_step(current * 0.97, tick, ROUND_DOWN)
    list_id = None
    cancelled = False
    try:
        placed = client.place_oco_order(
            symbol=symbol, side="SELL", quantity=sellable,
            take_profit_price=tp, stop_price=stop, stop_limit_price=stop_limit,
            client_order_id=f"nqoco-e2e-{os.getpid()}",
        )
        list_id = int(placed["orderListId"])
        assert list_id > 0
        detail = client.get_order_list(list_id)
        assert int(detail["orderListId"]) == list_id
        client.cancel_order_list(symbol=symbol, order_list_id=list_id)
        cancelled = True
        final = client.get_order_list(list_id)
        assert final.get("listStatusType") in {"ALL_DONE", "REJECT", "EXPIRED"}
        history = client.all_order_lists(limit=1000)
        assert any(int(item.get("orderListId", 0)) == list_id for item in history)
    finally:
        # Only sell the testnet quantity after confirmed OCO cancellation.
        if cancelled:
            remaining = _round_step(
                min(sellable, client.free_balance(base_asset)), lot["stepSize"], ROUND_DOWN,
            )
            if remaining > 0:
                client.place_market_order(
                    symbol=symbol, side="SELL", quantity=remaining,
                    client_order_id=f"nq-e2e-clean-{os.getpid()}",
                )
