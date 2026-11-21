"""Opt-in, bounded Binance Spot Testnet order/OCO lifecycle smoke test.

Never points at mainnet. Cleanup resolves ambiguous OCO responses and refuses a
competing market sell until the exchange confirms that protection is terminal.
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


def _not_found(exc: Exception) -> bool:
    body = str(getattr(exc, "binance_body", ""))
    return "-2013" in body or "Order does not exist" in body


def test_spot_testnet_market_oco_cancel_and_recovery_flow():
    key = os.getenv("BINANCE_API_KEY", "")
    secret = os.getenv("BINANCE_API_SECRET", "")
    symbol = os.getenv("NEXORA_TESTNET_SYMBOL", "BTCUSDT").upper()
    quote_amount = float(os.getenv("NEXORA_TESTNET_ORDER_QUOTE_USDT", "15"))
    if not key or not secret:
        pytest.fail("Testnet E2E requires BINANCE_API_KEY and BINANCE_API_SECRET")
    if not 19.99 <= quote_amount <= 20.01:
        pytest.fail("Testnet E2E is deliberately capped at 20 USDT")
    if not symbol.isalnum() or not 5 <= len(symbol) <= 20:
        pytest.fail("NEXORA_TESTNET_SYMBOL must be a plain Binance symbol")

    client = BinanceRestClient(api_key=key, api_secret=secret, testnet=True)
    assert client.testnet is True
    assert client.base == "https://testnet.binance.vision"
    client.ping()
    client.account()
    info = client.exchange_info_symbol(symbol)
    filters = {item["filterType"]: item for item in info.get("filters", [])}
    lot = filters.get("LOT_SIZE") or filters.get("MARKET_LOT_SIZE")
    market_lot = filters.get("MARKET_LOT_SIZE") or lot
    price_filter = filters.get("PRICE_FILTER")
    assert lot and market_lot and price_filter, "symbol missing required exchange filters"

    base_asset = str(info.get("baseAsset", "")).upper()
    assert base_asset
    # Isolate this test's acquired quantity from any pre-existing testnet balance.
    base_before = client.free_balance(base_asset)
    buy_client_id = f"nq-e2e-buy-{os.getpid()}"
    try:
        buy = client.place_market_order(
            symbol=symbol, side="BUY", quote_order_qty=quote_amount,
            client_order_id=buy_client_id,
        )
    except Exception:
        # Resolve by the same client ID; never blindly submit a second market buy.
        buy = client.get_order_by_client_id(symbol, buy_client_id)
    assert buy.order_id > 0 and buy.status in {"FILLED", "PARTIALLY_FILLED"}
    assert buy.executed_qty > 0

    list_id = None
    oco_client_id = f"nqoco-e2e-{os.getpid()}"
    cleanup_safe = False
    sellable = 0.0
    try:
        acquired = max(0.0, client.free_balance(base_asset) - base_before)
        sellable = _round_step(min(buy.executed_qty, acquired), lot["stepSize"], ROUND_DOWN)
        if sellable <= 0:
            raise RuntimeError("No newly acquired free base quantity available for OCO test")
        current = client.ticker_price(symbol)
        tick = price_filter["tickSize"]
        tp = _round_step(current * 1.02, tick, ROUND_UP)
        stop = _round_step(current * 0.98, tick, ROUND_DOWN)
        stop_limit = _round_step(current * 0.97, tick, ROUND_DOWN)
        placed = client.place_oco_order(
            symbol=symbol, side="SELL", quantity=sellable,
            take_profit_price=tp, stop_price=stop, stop_limit_price=stop_limit,
            client_order_id=oco_client_id, stop_loss_market=True,
        )
        list_id = int(placed["orderListId"])
        assert list_id > 0
        detail = client.get_order_list(list_id)
        assert int(detail["orderListId"]) == list_id
        client.cancel_order_list(symbol=symbol, order_list_id=list_id)
        final = client.get_order_list(list_id)
        assert final.get("listStatusType") in {"ALL_DONE", "REJECT", "EXPIRED"}
        cleanup_safe = True
        history = client.all_order_lists(limit=1000)
        assert any(int(item.get("orderListId", 0)) == list_id for item in history)
    finally:
        # A timed-out OCO POST may still have succeeded. Resolve by listClientOrderId.
        try:
            if list_id is None:
                try:
                    detail = client.get_order_list_by_client_id(symbol, oco_client_id)
                    list_id = int(detail["orderListId"])
                except Exception as exc:
                    if _not_found(exc):
                        cleanup_safe = True
                    else:
                        raise RuntimeError("Cannot resolve OCO state; leaving testnet funds untouched") from exc
            if list_id is not None:
                detail = client.get_order_list(list_id)
                if detail.get("listStatusType") in {"EXEC_STARTED", "EXECUTING"}:
                    client.cancel_order_list(symbol=symbol, order_list_id=list_id)
                    detail = client.get_order_list(list_id)
                cleanup_safe = detail.get("listStatusType") in {"ALL_DONE", "REJECT", "EXPIRED"}
            if not cleanup_safe:
                raise RuntimeError("OCO terminal/cancel state not confirmed; refusing market cleanup sell")
            remaining_free = max(0.0, client.free_balance(base_asset) - base_before)
            remaining = _round_step(
                min(sellable, remaining_free), market_lot["stepSize"], ROUND_DOWN,
            )
            if remaining > 0:
                cleanup_id = f"nq-e2e-clean-{os.getpid()}"
                try:
                    sold = client.place_market_order(
                        symbol=symbol, side="SELL", quantity=remaining,
                        client_order_id=cleanup_id,
                    )
                except Exception:
                    # The market sell may have executed despite a lost response.
                    sold = client.get_order_by_client_id(symbol, cleanup_id)
                if sold.status not in {"FILLED", "CANCELED", "EXPIRED", "REJECTED"}:
                    raise RuntimeError(f"Cleanup market sell is not terminal: {sold.status}")
        except Exception as cleanup_exc:
            pytest.fail(f"Testnet cleanup could not be confirmed: {cleanup_exc}")
