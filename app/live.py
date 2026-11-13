"""Live / testnet executor that places real Binance Spot market orders.

Uses the paper-compatible trade dict shape so storage and risk accounting stay shared.
"""
from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
from typing import Any

from app.binance_rest import BinanceRestClient, OrderResult

log = logging.getLogger(__name__)


class LiveExecutor:
    """Thin wrapper around signed REST orders with local position tracking."""

    def __init__(self, client: BinanceRestClient, symbol: str, *, fee_rate: float = 0.001) -> None:
        self.client = client
        self.symbol = symbol.upper()
        self.fee_rate = float(fee_rate)
        self.cash_usdt = 0.0
        self.base_quantity = 0.0
        self.average_entry_price = 0.0
        self.realized_pnl_usdt = 0.0
        self.trades: list[dict[str, Any]] = []
        self.order_state_uncertain = False
        self.unresolved_client_order_id: str | None = None
        self.protective_order_list_id: int | None = None
        self.order_lists_reconciled = True
        self.open_order_lists_snapshot: list[dict[str, Any]] = []
        self._order_lock = threading.Lock()
        self._order_sequence = 0
        self._filters: dict[str, Any] | None = None
        self.base_asset = self.symbol.replace("USDT", "")
        self.quote_asset = "USDT"
        self.sync_balances()

    def sync_balances(self) -> None:
        acc = self.client.account()
        balances = {b["asset"]: b for b in acc.get("balances", [])}
        usdt = balances.get("USDT", {})
        base = balances.get(self.base_asset, {})
        self.cash_usdt = float(usdt.get("free", 0))
        free_base = float(base.get("free", 0))
        if free_base <= 0:
            self.base_quantity = 0.0
            self.average_entry_price = 0.0
        else:
            self.base_quantity = free_base

    def _load_filters(self) -> dict[str, Any]:
        if self._filters is not None:
            return self._filters
        info = self.client.exchange_info(self.symbol)
        symbols = info.get("symbols") or []
        for s in symbols:
            if str(s.get("symbol", "")).upper() == self.symbol:
                out = {}
                for f in s.get("filters") or []:
                    out[str(f.get("filterType"))] = f
                self._filters = out
                return out
        self._filters = {}
        return self._filters

    def _round_step(self, qty: float) -> float:
        filters = self._load_filters()
        lot = filters.get("LOT_SIZE") or filters.get("MARKET_LOT_SIZE") or {}
        step = float(lot.get("stepSize") or 0.00001)
        if step <= 0:
            return qty
        precision = max(0, int(round(-math.log10(step)))) if step < 1 else 0
        stepped = math.floor(qty / step) * step
        return float(f"{stepped:.{precision}f}")

    def _round_price(self, price: float, *, round_up: bool) -> float:
        filters = self._load_filters()
        pf = filters.get("PRICE_FILTER") or {}
        tick = float(pf.get("tickSize") or 0.01)
        if tick <= 0:
            return price
        precision = max(0, int(round(-math.log10(tick)))) if tick < 1 else 0
        if round_up:
            stepped = math.ceil(price / tick) * tick
        else:
            stepped = math.floor(price / tick) * tick
        return float(f"{stepped:.{precision}f}")

    def _min_notional(self) -> float:
        filters = self._load_filters()
        mn = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
        return float(mn.get("minNotional") or mn.get("notional") or 5.0)

    def buy(
        self, *, notional_usdt: float, price: float, reason: str,
        decision_mid: float | None = None,
    ) -> dict:
        if notional_usdt <= 0 or price <= 0:
            raise ValueError("Price and notional must be positive")
        if notional_usdt < self._min_notional():
            raise ValueError(f"Notional below exchange minimum ({self._min_notional()})")
        result = self._place_market_order_once(
            side="BUY", reason=reason, quote_order_qty=notional_usdt,
        )
        return self._apply_fill(
            result, reason=reason, fallback_price=price,
            decision_mid=decision_mid if decision_mid is not None else price,
        )

    def sell_quantity(
        self, *, quantity: float, price: float, reason: str,
        decision_mid: float | None = None,
    ) -> dict | None:
        if price <= 0 or quantity <= 0:
            raise ValueError("Price and quantity must be positive")
        if self.base_quantity <= 0:
            return None
        qty = min(quantity, self.base_quantity)
        qty = self._round_step(qty)
        if qty <= 0:
            return None
        result = self._place_market_order_once(
            side="SELL", reason=reason, quantity=qty,
        )
        return self._apply_fill(
            result, reason=reason, fallback_price=price,
            decision_mid=decision_mid if decision_mid is not None else price,
        )

    def _place_market_order_once(
        self, *, side: str, reason: str,
        quantity: float | None = None, quote_order_qty: float | None = None,
    ) -> OrderResult:
        with self._order_lock:
            if self.order_state_uncertain:
                raise RuntimeError(
                    "Order state is uncertain; reconcile exchange orders before new orders"
                )
            self._order_sequence += 1
            client_id = f"nq{side[0].lower()}{time.time_ns():x}"[:36]
            try:
                return self.client.place_market_order(
                    symbol=self.symbol,
                    side=side,
                    quantity=quantity,
                    quote_order_qty=quote_order_qty,
                    client_order_id=client_id,
                )
            except Exception:
                self.order_state_uncertain = True
                self.unresolved_client_order_id = client_id
                log.exception("Market order failed; marking state uncertain")
                raise

    def _apply_fill(
        self,
        result: OrderResult,
        *,
        reason: str,
        fallback_price: float,
        decision_mid: float,
    ) -> dict:
        # Simplified accounting path compatible with paper trade dicts.
        executed_qty = float(result.executed_qty or 0)
        quote = float(result.cummulative_quote_qty or 0)
        fill_price = (quote / executed_qty) if executed_qty > 0 else float(fallback_price)
        side = result.side.upper()
        fee = abs(quote) * self.fee_rate if quote else executed_qty * fill_price * self.fee_rate
        trade = {
            "side": side.lower(),
            "price": fill_price,
            "quantity": executed_qty,
            "notional_usdt": quote if quote else executed_qty * fill_price,
            "fee_usdt": fee,
            "reason": reason,
            "timestamp": time.time(),
            "order_id": result.order_id,
            "client_order_id": result.client_order_id,
            "status": result.status,
            "decision_mid": decision_mid,
            "accounting_complete": True,
            "execution_latency_measured": False,
        }
        if side == "BUY" and executed_qty > 0:
            total_cost = self.average_entry_price * self.base_quantity + fill_price * executed_qty
            self.base_quantity += executed_qty
            self.average_entry_price = total_cost / self.base_quantity if self.base_quantity else 0.0
            self.cash_usdt = max(0.0, self.cash_usdt - trade["notional_usdt"] - fee)
        elif side == "SELL" and executed_qty > 0:
            pnl = (fill_price - self.average_entry_price) * executed_qty - fee
            trade["pnl_usdt"] = pnl
            self.realized_pnl_usdt += pnl
            self.base_quantity = max(0.0, self.base_quantity - executed_qty)
            if self.base_quantity <= 1e-12:
                self.base_quantity = 0.0
                self.average_entry_price = 0.0
            self.cash_usdt += trade["notional_usdt"] - fee
        self.trades.append(trade)
        self.sync_balances()
        return trade

    def snapshot(self, mark: float | None = None) -> dict[str, Any]:
        mark_px = float(mark or self.average_entry_price or 0)
        equity = self.cash_usdt + self.base_quantity * mark_px
        return {
            "cash_usdt": self.cash_usdt,
            "base_quantity": self.base_quantity,
            "average_entry_price": self.average_entry_price,
            "equity_usdt": equity,
            "realized_pnl_usdt": self.realized_pnl_usdt,
            "mode": "live",
            "testnet": self.client.testnet,
        }
