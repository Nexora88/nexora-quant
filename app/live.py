"""Live / testnet executor that places real Binance Spot market orders.

Uses the paper-compatible trade dict shape so storage and risk accounting stay shared.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from app.binance_rest import BinanceRestClient, OrderResult

log = logging.getLogger(__name__)


class LiveExecutor:
    """Tracks local mirror of position while orders go to the exchange."""

    def __init__(
        self,
        client: BinanceRestClient,
        *,
        symbol: str,
        fee_rate: float,
        base_asset: str | None = None,
        quote_asset: str = "USDT",
    ) -> None:
        if not 0 <= fee_rate < 0.1:
            raise ValueError("Invalid fee rate")
        self.client = client
        self.symbol = symbol.upper()
        self.fee_rate = fee_rate
        self.quote_asset = quote_asset.upper()
        self.base_asset = (base_asset or self.symbol.replace(self.quote_asset, "")).upper()
        self.starting_cash_usdt = 0.0
        self.cash_usdt = 0.0
        self.base_quantity = 0.0
        self.average_entry_price = 0.0
        self.realized_pnl_usdt = 0.0
        self.fees_paid_usdt = 0.0
        self.trades: list[dict[str, Any]] = []
        self._filters: dict[str, Any] | None = None
        self._order_lock = threading.RLock()
        self._order_sequence = 0
        self.order_state_uncertain = False
        self.unresolved_client_order_id: str | None = None
        self.locked_base_quantity = 0.0
        self.locked_quote_balance = 0.0
        self.open_orders_snapshot: list[dict[str, Any]] = []
        self.open_order_lists_snapshot: list[dict[str, Any]] = []

    def sync_balances(self) -> None:
        """Reconcile local balances and open orders against the exchange account."""
        account = self.client.account()
        balances = {str(b.get("asset", "")).upper(): b for b in account.get("balances", [])}
        quote = balances.get(self.quote_asset, {})
        base = balances.get(self.base_asset, {})
        self.cash_usdt = float(quote.get("free", 0))
        self.locked_quote_balance = float(quote.get("locked", 0))
        base_free = float(base.get("free", 0))
        self.locked_base_quantity = float(base.get("locked", 0))
        self.base_quantity = base_free + self.locked_base_quantity
        self.open_orders_snapshot = self.client.open_orders(self.symbol)
        try:
            self.open_order_lists_snapshot = self.client.open_order_lists()
        except Exception:
            self.open_order_lists_snapshot = []
            log.warning("Could not reconcile exchange order lists", exc_info=True)
        if self.starting_cash_usdt <= 0:
            self.starting_cash_usdt = self.cash_usdt + self.locked_quote_balance
        log.info(
            "Live balances synced: %s=%.8f %s=%.4f (testnet=%s)",
            self.base_asset,
            self.base_quantity,
            self.quote_asset,
            self.cash_usdt,
            self.client.testnet,
        )

    def restore(self, snapshot: dict[str, Any]) -> None:
        numeric = (
            "starting_cash_usdt",
            "cash_usdt",
            "base_quantity",
            "average_entry_price",
            "realized_pnl_usdt",
            "fees_paid_usdt",
        )
        values = {key: float(snapshot.get(key, 0)) for key in numeric}
        self.starting_cash_usdt = values["starting_cash_usdt"]
        self.cash_usdt = values["cash_usdt"]
        self.base_quantity = values["base_quantity"]
        self.average_entry_price = values["average_entry_price"]
        self.realized_pnl_usdt = values["realized_pnl_usdt"]
        self.fees_paid_usdt = values["fees_paid_usdt"]
        self.trades = list(snapshot.get("trades", []))
        self._order_sequence = int(snapshot.get("order_sequence", 0))
        self.order_state_uncertain = bool(snapshot.get("order_state_uncertain", False))
        self.unresolved_client_order_id = snapshot.get("unresolved_client_order_id")

    def _load_filters(self) -> dict[str, Any]:
        if self._filters is not None:
            return self._filters
        info = self.client.exchange_info_symbol(self.symbol)
        filters = {f["filterType"]: f for f in info.get("filters", [])}
        self._filters = filters
        return filters

    def _round_step(self, quantity: float) -> float:
        filters = self._load_filters()
        lot = filters.get("LOT_SIZE") or filters.get("MARKET_LOT_SIZE") or {}
        step = float(lot.get("stepSize") or 0.00000001)
        if step <= 0:
            return quantity
        precision = max(0, len(f"{step:.12f}".rstrip("0").split(".")[-1]) if "." in f"{step:.12f}" else 0)
        steps = int(quantity / step)
        return round(steps * step, precision)

    def _min_notional(self) -> float:
        filters = self._load_filters()
        mn = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
        return float(mn.get("minNotional") or mn.get("notional") or 5.0)

    def buy(self, *, notional_usdt: float, price: float, reason: str) -> dict:
        if notional_usdt <= 0 or price <= 0:
            raise ValueError("Price and notional must be positive")
        if notional_usdt < self._min_notional():
            raise ValueError(f"Notional below exchange minimum ({self._min_notional()})")
        result = self._place_market_order_once(
            side="BUY", reason=reason, quote_order_qty=notional_usdt,
        )
        return self._apply_fill(result, reason=reason, fallback_price=price)

    def sell_quantity(self, *, quantity: float, price: float, reason: str) -> dict | None:
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
        return self._apply_fill(result, reason=reason, fallback_price=price)

    def _place_market_order_once(
        self, *, side: str, reason: str,
        quantity: float | None = None, quote_order_qty: float | None = None,
    ) -> OrderResult:
        """Use a stable client ID and fail closed if an order's outcome is unknown."""
        with self._order_lock:
            if self.order_state_uncertain:
                raise RuntimeError(
                    "Order state is uncertain; reconcile exchange orders before new orders"
                )
            amount = quote_order_qty if quote_order_qty is not None else quantity
            digest = hashlib.sha256(
                f"{self.symbol}|{side}|{reason}|{amount:.12f}|{self._order_sequence}".encode()
            ).hexdigest()[:18]
            client_id = f"nq{self._order_sequence:x}{digest}"[:36]
            try:
                existing = self.client.get_order_by_client_id(self.symbol, client_id)
            except Exception as exc:
                if "-2013" not in str(exc) and "Order does not exist" not in str(exc):
                    raise
            else:
                self._order_sequence += 1
                return existing
            try:
                result = self.client.place_market_order(
                    symbol=self.symbol, side=side, quantity=quantity,
                    quote_order_qty=quote_order_qty, client_order_id=client_id,
                )
            except Exception:
                try:
                    result = self.client.get_order_by_client_id(self.symbol, client_id)
                except Exception:
                    self.order_state_uncertain = True
                    self.unresolved_client_order_id = client_id
                    log.exception(
                        "Order submission outcome uncertain; blocking further orders (%s)",
                        client_id,
                    )
                    raise
            self._order_sequence += 1
            return result

    def reconcile_uncertain_order(self) -> bool:
        """Resolve a timed-out submission by its client ID; never blindly resubmit."""
        with self._order_lock:
            if not self.order_state_uncertain:
                return True
            client_id = self.unresolved_client_order_id
            if not client_id:
                return False
            try:
                order = self.client.get_order_by_client_id(self.symbol, client_id)
            except Exception:
                return False
            log.warning(
                "Recovered uncertain order clientId=%s orderId=%s status=%s; "
                "inspect/reconcile its fill before allowing strategy orders",
                client_id, order.order_id, order.status,
            )
            # A recovered exchange order is not yet proof of local accounting.
            # Keep the gate closed until a full fill/balance reconciliation occurs.
            return False

    def sell_all(self, *, price: float, reason: str = "manual_live_exit") -> dict | None:
        return self.sell_quantity(quantity=self.base_quantity, price=price, reason=reason)

    def _apply_fill(self, result: OrderResult, *, reason: str, fallback_price: float) -> dict:
        executed_qty = float(result.executed_qty)
        quote = float(result.cummulative_quote_qty)
        if executed_qty <= 0:
            raise RuntimeError(f"Order not filled: status={result.status} id={result.order_id}")
        fee_usdt = 0.0
        if result.fills:
            total_cost = 0.0
            total_qty = 0.0
            for f in result.fills:
                p = float(f.get("price", 0))
                q = float(f.get("qty", 0))
                total_cost += p * q
                total_qty += q
                commission = float(f.get("commission", 0))
                commission_asset = str(f.get("commissionAsset", "")).upper()
                if commission_asset == self.quote_asset:
                    fee_usdt += commission
                elif commission_asset == self.base_asset:
                    fee_usdt += commission * p
            avg_price = (total_cost / total_qty) if total_qty else fallback_price
            executed_qty = total_qty or executed_qty
            quote = total_cost or quote
        else:
            avg_price = (quote / executed_qty) if executed_qty else fallback_price
            fee_usdt = quote * self.fee_rate
        side = result.side.lower()
        trade: dict[str, Any] = {
            "side": side,
            "price": avg_price,
            "quantity": executed_qty,
            "notional_usdt": quote,
            "fee_usdt": fee_usdt,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "exchange_order_id": result.order_id,
            "client_order_id": result.client_order_id,
            "status": result.status,
            "testnet": self.client.testnet,
        }
        if side == "buy":
            old_cost = self.base_quantity * self.average_entry_price
            self.base_quantity += executed_qty
            self.average_entry_price = (old_cost + quote) / self.base_quantity if self.base_quantity else 0.0
            self.cash_usdt = max(0.0, self.cash_usdt - quote - fee_usdt)
            self.fees_paid_usdt += fee_usdt
        else:
            pnl = (avg_price - self.average_entry_price) * executed_qty - fee_usdt
            self.cash_usdt += quote - fee_usdt
            self.realized_pnl_usdt += pnl
            self.fees_paid_usdt += fee_usdt
            trade["pnl_usdt"] = pnl
            self.base_quantity = max(0.0, self.base_quantity - executed_qty)
            if self.base_quantity < 1e-12:
                self.base_quantity = 0.0
                self.average_entry_price = 0.0
        self.trades.append(trade)
        log.info(
            "LIVE %s filled qty=%.8f price=%.4f notional=%.4f fee=%.6f orderId=%s testnet=%s",
            side.upper(), executed_qty, avg_price, quote, fee_usdt, result.order_id, self.client.testnet,
        )
        return trade

    def snapshot(self, mark_price: float | None = None) -> dict:
        mark = mark_price or self.average_entry_price
        market_value = self.base_quantity * mark
        unrealized = (
            (mark - self.average_entry_price) * self.base_quantity
            if self.base_quantity and mark
            else 0.0
        )
        return {
            "starting_cash_usdt": self.starting_cash_usdt,
            "cash_usdt": self.cash_usdt,
            "base_quantity": self.base_quantity,
            "average_entry_price": self.average_entry_price,
            "market_value_usdt": market_value,
            "equity_usdt": self.cash_usdt + market_value,
            "unrealized_pnl_usdt": unrealized,
            "realized_pnl_usdt": self.realized_pnl_usdt,
            "fees_paid_usdt": self.fees_paid_usdt,
            "trade_count": len(self.trades),
            "trades": self.trades[-100:],
            "order_sequence": self._order_sequence,
            "order_state_uncertain": self.order_state_uncertain,
            "unresolved_client_order_id": self.unresolved_client_order_id,
            "locked_base_quantity": self.locked_base_quantity,
            "locked_quote_balance": self.locked_quote_balance,
            "open_orders_count": len(self.open_orders_snapshot),
            "open_order_lists_count": len(self.open_order_lists_snapshot),
            "mode": "live",
            "testnet": self.client.testnet,
        }
