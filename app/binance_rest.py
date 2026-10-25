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
            data = query.encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
                method=method,
            )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            log.error("Binance REST %s %s failed: %s %s", method, path, exc.code, err_body)
            raise RuntimeError(f"Binance API error {exc.code}: {err_body}") from exc

    def ping(self) -> dict[str, Any]:
        return self._request("GET", "/api/v3/ping")

    def account(self) -> dict[str, Any]:
        return self._request("GET", "/api/v3/account", signed=True)

    def free_balance(self, asset: str) -> float:
        info = self.account()
        asset = asset.upper()
        for bal in info.get("balances", []):
            if bal.get("asset") == asset:
                return float(bal.get("free", 0))
        return 0.0

    def exchange_info_symbol(self, symbol: str) -> dict[str, Any]:
        data = self._request("GET", "/api/v3/exchangeInfo", {"symbol": symbol.upper()})
        symbols = data.get("symbols") or []
        if not symbols:
            raise ValueError(f"Unknown symbol {symbol}")
        return symbols[0]

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

    def get_order(self, symbol: str, order_id: int) -> OrderResult:
        raw = self._request(
            "GET", "/api/v3/order",
            {"symbol": symbol.upper(), "orderId": order_id}, signed=True,
        )
        return _parse_order(raw)

    def place_oco_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        take_profit_price: float,
        stop_price: float,
        stop_limit_price: float | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        """Exchange-hosted OCO so TP/SL survive bot disconnects."""
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        stop_limit = stop_limit_price if stop_limit_price is not None else stop_price
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side,
            "quantity": _fmt_qty(quantity),
            "price": _fmt_qty(take_profit_price),
            "stopPrice": _fmt_qty(stop_price),
            "stopLimitPrice": _fmt_qty(stop_limit),
            "stopLimitTimeInForce": "GTC",
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
        limit_price: float | None = None,
    ) -> dict[str, Any]:
        side = side.upper()
        limit_price = limit_price if limit_price is not None else stop_price
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side,
            "type": "STOP_LOSS_LIMIT",
            "quantity": _fmt_qty(quantity),
            "stopPrice": _fmt_qty(stop_price),
            "price": _fmt_qty(limit_price),
            "timeInForce": "GTC",
        }
        return self._request("POST", "/api/v3/order", params, signed=True)


def _fmt_qty(value: float) -> str:
    s = f"{value:.12f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _parse_order(raw: dict[str, Any]) -> OrderResult:
    return OrderResult(
        order_id=int(raw.get("orderId", 0)),
        client_order_id=str(raw.get("clientOrderId", "")),
        symbol=str(raw.get("symbol", "")),
        side=str(raw.get("side", "")),
        status=str(raw.get("status", "")),
        price=float(raw.get("price") or 0),
        orig_qty=float(raw.get("origQty") or 0),
        executed_qty=float(raw.get("executedQty") or 0),
        cummulative_quote_qty=float(raw.get("cummulativeQuoteQty") or 0),
        fills=list(raw.get("fills") or []),
        raw=raw,
    )
