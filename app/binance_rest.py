"""Signed Binance Spot REST client (stdlib only). Supports mainnet and testnet.

WARNING: Live mode places real orders with real funds when testnet is disabled.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

MAINNET_REST = "https://api.binance.com"
TESTNET_REST = "https://testnet.binance.vision"


@dataclass(frozen=True, slots=True)
class OrderResult:
    order_id: int
    client_order_id: str
    symbol: str
    side: str
    status: str
    price: float
    orig_qty: float
    executed_qty: float
    cummulative_quote_qty: float
    fills: list[dict[str, Any]]
    raw: dict[str, Any]


def _fmt_qty(value: float) -> str:
    text = f"{value:.12f}".rstrip("0").rstrip(".")
    return text or "0"


def _parse_order(raw: dict[str, Any]) -> OrderResult:
    fills = raw.get("fills") if isinstance(raw.get("fills"), list) else []
    return OrderResult(
        order_id=int(raw.get("orderId") or 0),
        client_order_id=str(raw.get("clientOrderId") or ""),
        symbol=str(raw.get("symbol") or ""),
        side=str(raw.get("side") or ""),
        status=str(raw.get("status") or ""),
        price=float(raw.get("price") or 0),
        orig_qty=float(raw.get("origQty") or 0),
        executed_qty=float(raw.get("executedQty") or 0),
        cummulative_quote_qty=float(raw.get("cummulativeQuoteQty") or 0),
        fills=list(fills),
        raw=raw,
    )


class BinanceRestClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        testnet: bool = True,
        recv_window: int = 5000,
        timeout: float = 15.0,
    ) -> None:
        if not api_key or not api_secret:
            raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET are required for live mode")
        self.api_key = api_key
        self.api_secret = api_secret.encode("utf-8")
        self.base = TESTNET_REST if testnet else MAINNET_REST
        self.recv_window = recv_window
        self.timeout = timeout
        self.testnet = testnet

    def _sign(self, params: dict[str, Any]) -> str:
        query = urllib.parse.urlencode(params, doseq=True)
        return hmac.new(self.api_secret, query.encode("utf-8"), hashlib.sha256).hexdigest()

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        signed: bool = False,
    ) -> dict[str, Any]:
        params = dict(params or {})
        headers = {"User-Agent": "NexoraQuant/0.2", "X-MBX-APIKEY": self.api_key}
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = self.recv_window
            params["signature"] = self._sign(params)
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{self.base}{path}"
        if method == "GET":
            full = f"{url}?{query}" if query else url
            req = urllib.request.Request(full, headers=headers, method="GET")
        else:
            req = urllib.request.Request(
                url, data=query.encode("utf-8"), headers=headers, method=method
            )
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            log.error("Binance HTTP %s %s: %s", exc.code, path, err_body[:500])
            raise

    def exchange_info(self, symbol: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol.upper()
        return self._request("GET", "/api/v3/exchangeInfo", params)

    def account(self) -> dict[str, Any]:
        return self._request("GET", "/api/v3/account", signed=True)

    def place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float | None = None,
        quote_order_qty: float | None = None,
        client_order_id: str | None = None,
    ) -> OrderResult:
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side,
            "type": "MARKET",
            "newOrderRespType": "FULL",
        }
        if quantity is not None:
            params["quantity"] = _fmt_qty(quantity)
        if quote_order_qty is not None:
            params["quoteOrderQty"] = _fmt_qty(quote_order_qty)
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        if "quantity" not in params and "quoteOrderQty" not in params:
            raise ValueError("quantity or quoteOrderQty required")
        raw = self._request("POST", "/api/v3/order", params, signed=True)
        return _parse_order(raw)

    def place_limit_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        client_order_id: str | None = None,
        post_only: bool = True,
        time_in_force: str = "GTC",
    ) -> OrderResult:
        """LIMIT or LIMIT_MAKER (post-only). Rejects if it would take liquidity when post_only."""
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        if quantity <= 0 or price <= 0:
            raise ValueError("quantity and price must be positive")
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side,
            "type": "LIMIT_MAKER" if post_only else "LIMIT",
            "quantity": _fmt_qty(quantity),
            "price": _fmt_qty(price),
            "newOrderRespType": "FULL",
        }
        if not post_only:
            params["timeInForce"] = time_in_force
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        raw = self._request("POST", "/api/v3/order", params, signed=True)
        return _parse_order(raw)

    def get_order(self, symbol: str, order_id: int) -> OrderResult:
        raw = self._request(
            "GET", "/api/v3/order",
            {"symbol": symbol.upper(), "orderId": order_id}, signed=True,
        )
        return _parse_order(raw)

    def cancel_order(
        self, *, symbol: str, order_id: int | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        if order_id is None and not client_order_id:
            raise ValueError("order_id or client_order_id is required")
        params: dict[str, Any] = {"symbol": symbol.upper()}
        if order_id is not None:
            params["orderId"] = order_id
        if client_order_id:
            params["origClientOrderId"] = client_order_id
        return self._request("DELETE", "/api/v3/order", params, signed=True)

    def open_order_lists(self) -> list[dict[str, Any]]:
        raw = self._request("GET", "/api/v3/openOrderList", signed=True)
        if not isinstance(raw, list):
            raise RuntimeError("Unexpected openOrderList response")
        return raw

    def cancel_order_list(self, *, symbol: str, order_list_id: int) -> dict[str, Any]:
        return self._request(
            "DELETE", "/api/v3/orderList",
            {"symbol": symbol.upper(), "orderListId": order_list_id}, signed=True,
        )

    def place_oco_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        take_profit_price: float,
        stop_price: float,
        stop_limit_price: float,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "quantity": _fmt_qty(quantity),
            "aboveType": "LIMIT_MAKER",
            "abovePrice": _fmt_qty(take_profit_price),
            "belowType": "STOP_LOSS_LIMIT",
            "belowStopPrice": _fmt_qty(stop_price),
            "belowPrice": _fmt_qty(stop_limit_price),
            "belowTimeInForce": "GTC",
        }
        if client_order_id:
            params["listClientOrderId"] = client_order_id
        return self._request("POST", "/api/v3/orderList/oco", params, signed=True)

    def place_stop_loss_limit(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
        price: float,
        client_order_id: str | None = None,
    ) -> OrderResult:
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "STOP_LOSS_LIMIT",
            "quantity": _fmt_qty(quantity),
            "stopPrice": _fmt_qty(stop_price),
            "price": _fmt_qty(price),
            "timeInForce": "GTC",
            "newOrderRespType": "FULL",
        }
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        raw = self._request("POST", "/api/v3/order", params, signed=True)
        return _parse_order(raw)

    def get_order_list(self, order_list_id: int) -> dict[str, Any]:
        raw = self._request(
            "GET", "/api/v3/orderList", {"orderListId": order_list_id}, signed=True,
        )
        if not isinstance(raw, dict) or not raw.get("orderListId"):
            raise RuntimeError("Unexpected orderList response")
        return raw

    def order_trades(self, symbol: str, order_id: int) -> list[dict[str, Any]]:
        raw = self._request(
            "GET", "/api/v3/myTrades",
            {"symbol": symbol.upper(), "orderId": order_id}, signed=True,
        )
        if not isinstance(raw, list):
            raise RuntimeError("Unexpected myTrades response")
        return raw

    def order_list_trades(self, symbol: str, order_id: int) -> list[dict[str, Any]]:
        return self.order_trades(symbol, order_id)

    def all_order_list(self, *, from_id: int | None = None, limit: int = 500) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        while True:
            params: dict[str, Any] = {"limit": limit}
            if from_id is not None:
                params["fromId"] = from_id
            batch = self._request("GET", "/api/v3/allOrderList", params, signed=True)
            if not isinstance(batch, list):
                raise RuntimeError("Unexpected allOrderList response")
            result.extend(batch)
            if len(batch) < limit:
                return result
            ids = [int(item.get("orderListId", 0)) for item in batch]
            next_id = max(ids, default=0) + 1
            if next_id <= (from_id or 0):
                raise RuntimeError("allOrderList pagination did not advance")
            from_id = next_id
        raise RuntimeError("allOrderList history may be truncated; reconciliation blocked")
