"""Live / testnet executor that places real Binance Spot market orders.

Uses the paper-compatible trade dict shape so storage and risk accounting stay shared.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any
from uuid import uuid4

from app.binance_rest import BinanceRestClient, OrderResult
from app.live_reconciliation import live_trade_event_key
from app.order_state import OrderStateMachine
from app.storage import PaperStore

log = logging.getLogger(__name__)
TERMINAL_ORDER_STATUSES = frozenset({
    "FILLED", "CANCELED", "EXPIRED", "EXPIRED_IN_MATCH", "REJECTED",
})


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
        self.order_state_machine = OrderStateMachine()
        self.locked_base_quantity = 0.0
        self.locked_quote_balance = 0.0
        self.open_orders_snapshot: list[dict[str, Any]] = []
        self.open_order_lists_snapshot: list[dict[str, Any]] = []
        self.protective_order_list_id: int | None = None
        self.protective_order_client_id: str | None = None
        self.order_lists_reconciled = False
        # Exchange trade IDs are durable idempotency keys for offline OCO recovery.
        self.processed_exchange_trade_ids: set[str] = set()
        self.processed_oco_list_ids: set[int] = set()
        self._order_store: PaperStore | None = None
        self._order_store_key = ""
        self._checkpoint_trade_count = 0

    def sync_balances(self) -> None:
        """Reconcile OCO history before replacing the local ledger with account balances."""
        account = self.client.account()
        balances = {str(b.get("asset", "")).upper(): b for b in account.get("balances", [])}
        open_orders = self.client.open_orders(self.symbol)
        try:
            open_lists = self.client.open_order_lists()
            history = self.client.all_order_lists(limit=1000)
        except Exception as exc:
            self.order_lists_reconciled = False
            log.error("Could not reconcile exchange order-list history; live actions blocked", exc_info=True)
            raise RuntimeError("Exchange order-list history could not be reconciled") from exc

        self.open_orders_snapshot = open_orders
        self.open_order_lists_snapshot = open_lists
        self.order_lists_reconciled = True
        active_lists = [
            item for item in open_lists
            if str(item.get("symbol", "")).upper() == self.symbol
            and item.get("listStatusType") in ("EXEC_STARTED", "EXECUTING")
            and (
                str(item.get("listClientOrderId", "")).startswith("nqoco")
                or int(item.get("orderListId", 0)) == self.protective_order_list_id
            )
        ]
        if active_lists:
            self.protective_order_list_id = int(active_lists[-1]["orderListId"])
        else:
            self.protective_order_list_id = None
            # Recover the crash window where an OCO was accepted/completed but its
            # ID was not included in the last local snapshot.
            candidates = [
                item for item in history
                if str(item.get("symbol", "")).upper() == self.symbol
                and str(item.get("listClientOrderId", "")).startswith("nqoco")
                and int(item.get("orderListId", 0)) not in self.processed_oco_list_ids
                and item.get("listStatusType") in {"ALL_DONE", "REJECT", "EXPIRED"}
            ]
            if candidates:
                self.protective_order_list_id = int(candidates[-1]["orderListId"])
                if not self.reconcile_protective_oco():
                    raise RuntimeError("Historical OCO fills could not be reconciled; live actions blocked")

        quote = balances.get(self.quote_asset, {})
        base = balances.get(self.base_asset, {})
        self.cash_usdt = float(quote.get("free", 0))
        self.locked_quote_balance = float(quote.get("locked", 0))
        base_free = float(base.get("free", 0))
        self.locked_base_quantity = float(base.get("locked", 0))
        self.base_quantity = base_free + self.locked_base_quantity
        if self.base_quantity <= 1e-12:
            self.base_quantity = 0.0
            self.average_entry_price = 0.0
        if self.base_quantity > 0 and self.average_entry_price <= 0:
            # Exchange balances alone do not reconstruct the strategy's cost basis
            # or historical fills. Never resume strategy management as if accounting
            # were complete after a restart with an existing position.
            raise RuntimeError(
                "Existing base-asset position has no restored cost basis; "
                "reconcile exchange trades and accounting before resuming"
            )
        if open_orders and self.protective_order_list_id is None:
            raise RuntimeError("Unmanaged exchange open orders found; live trading blocked")
        if self.starting_cash_usdt <= 0:
            self.starting_cash_usdt = self.cash_usdt + self.locked_quote_balance
        log.info(
            "Live balances synced: %s=%.8f %s=%.4f (testnet=%s)",
            self.base_asset, self.base_quantity, self.quote_asset, self.cash_usdt,
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
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("Live snapshot contains non-finite accounting values")
        if values["cash_usdt"] < -1e-8 or values["base_quantity"] < 0:
            raise ValueError("Live snapshot contains a negative balance")
        if values["average_entry_price"] < 0 or values["fees_paid_usdt"] < 0:
            raise ValueError("Live snapshot contains invalid cost/fee values")
        if (values["base_quantity"] > 1e-12) != (values["average_entry_price"] > 0):
            raise ValueError("Live snapshot position and cost basis are inconsistent")
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
        self.order_state_machine.restore(snapshot.get("order_state_machine") or {})
        if self.order_state_uncertain:
            self.order_state_machine.force_unknown(self.unresolved_client_order_id)
        self.processed_exchange_trade_ids = {
            str(item) for item in snapshot.get("processed_exchange_trade_ids", [])
        }
        self.processed_oco_list_ids = {
            int(item) for item in snapshot.get("processed_oco_list_ids", [])
        }
        self.protective_order_client_id = snapshot.get("protective_order_client_id")

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
        steps = (Decimal(str(quantity)) / Decimal(str(step))).to_integral_value(
            rounding=ROUND_DOWN,
        )
        rounded = float(steps * Decimal(str(step)))
        return round(rounded, precision)

    def _round_price(self, price: float, *, round_up: bool) -> float:
        filters = self._load_filters()
        tick = float((filters.get("PRICE_FILTER") or {}).get("tickSize") or 0.00000001)
        if tick <= 0:
            return price
        units = price / tick
        rounded = math.ceil(units - 1e-10) if round_up else math.floor(units + 1e-10)
        precision = max(0, len(f"{tick:.12f}".rstrip("0").split(".")[-1]) if "." in f"{tick:.12f}" else 0)
        return round(rounded * tick, precision)

    def ensure_protective_oco(
        self, *, current_price: float, take_profit_pct: float, stop_loss_pct: float,
    ) -> bool:
        """Place exchange-hosted sell OCO; protection remains on exchange if app stops."""
        if current_price <= 0 or not 0 < take_profit_pct < 100 or not 0 < stop_loss_pct < 100:
            return False
        if self.order_state_uncertain:
            return False
        if self.protective_order_list_id is not None:
            return True
        try:
            available = self._round_step(self.client.free_balance(self.base_asset))
            if available <= 0:
                return False
            take_profit = self._round_price(
                self.average_entry_price * (1 + take_profit_pct / 100), round_up=True,
            )
            stop_price = self._round_price(
                self.average_entry_price * (1 - stop_loss_pct / 100), round_up=False,
            )
            stop_limit = self._round_price(stop_price * 0.999, round_up=False)
            if take_profit <= current_price or stop_price >= current_price or stop_limit <= 0:
                log.error("OCO prices invalid relative to current market; protection not installed")
                return False
            response = self.client.place_oco_order(
                symbol=self.symbol, side="SELL", quantity=available,
                take_profit_price=take_profit, stop_price=stop_price,
                stop_limit_price=stop_limit,
                client_order_id=f"nqoco{time.time_ns():x}"[:36],
            )
            self.protective_order_list_id = int(response.get("orderListId", 0)) or None
            self.open_order_lists_snapshot.append(response)
            if self.protective_order_list_id is not None:
                self._order_sequence += 1
            if self.protective_order_list_id is None:
                return False
            log.info(
                "Exchange OCO installed listId=%s qty=%.8f TP=%.8f stop=%.8f",
                self.protective_order_list_id, available, take_profit, stop_price,
            )
            return True
        except Exception:
            log.exception("Failed to install exchange-hosted TP/SL OCO")
            return False

    def reconcile_protective_oco(self) -> bool:
        """Recover completed OCO fills after downtime; refuse incomplete history.

        The caller must persist snapshot() immediately after a successful return.
        Repeated calls are idempotent by exchange trade ID.
        """
        list_id = self.protective_order_list_id
        if self.order_state_uncertain and self.unresolved_client_order_id:
            return False
        if list_id is None:
            return self.order_lists_reconciled
        try:
            order_list = self.client.get_order_list(list_id)
            if str(order_list.get("symbol", "")).upper() != self.symbol:
                raise RuntimeError("OCO history symbol mismatch")
            status = str(order_list.get("listStatusType", ""))
            if status in {"EXEC_STARTED", "EXECUTING"}:
                # Active lists are still protecting the position; do not account them as fills.
                self.order_lists_reconciled = True
                return True
            if status not in {"ALL_DONE", "REJECT", "EXPIRED"}:
                raise RuntimeError(f"Unknown OCO list status: {status or 'missing'}")
            reports = order_list.get("orderReports")
            if not isinstance(reports, list) or len(reports) != 2:
                raise RuntimeError("OCO history must contain both child order reports")
            recovered: list[dict[str, Any]] = []
            for report in reports:
                order_id = int(report.get("orderId", 0))
                if order_id <= 0:
                    raise RuntimeError("OCO child order has no exchange order ID")
                child = self.client.get_order(self.symbol, order_id)
                if child.status not in {"FILLED", "CANCELED", "EXPIRED", "REJECTED"}:
                    raise RuntimeError("OCO child order is not terminal")
                fills = self.client.order_list_trades(self.symbol, order_id)
                if child.executed_qty > 0:
                    if not fills or len(fills) >= 1000:
                        raise RuntimeError("OCO child trade history is missing or may be truncated")
                    filled_qty = sum(float(t.get("qty", 0)) for t in fills)
                    if not math.isclose(filled_qty, child.executed_qty, rel_tol=1e-8, abs_tol=1e-10):
                        raise RuntimeError("OCO trade quantities do not reconcile with child order")
                    for fill in fills:
                        if str(fill.get("isBuyer", "false")).lower() == "true":
                            raise RuntimeError("Unexpected BUY fill in protective SELL OCO")
                        recovered.append(fill)
            # Validate every commission before mutating local accounting, avoiding partial recovery.
            for fill in recovered:
                asset = str(fill.get("commissionAsset", "")).upper()
                commission = float(fill.get("commission", 0))
                if asset and commission and asset not in (self.base_asset, self.quote_asset):
                    raise RuntimeError(f"Cannot value commission asset {asset} from quote-only accounting")
            recovered.sort(key=lambda t: (int(t.get("time", 0)), int(t.get("id", 0))))
            for fill in recovered:
                trade_id = str(fill.get("id", ""))
                if not trade_id:
                    raise RuntimeError("Exchange trade is missing its trade ID")
                if trade_id in self.processed_exchange_trade_ids:
                    continue
                qty = float(fill.get("qty", 0))
                price = float(fill.get("price", 0))
                quote = float(fill.get("quoteQty", qty * price))
                if qty <= 0 or price <= 0 or quote <= 0:
                    raise RuntimeError("Invalid OCO fill values")
                asset = str(fill.get("commissionAsset", "")).upper()
                commission = float(fill.get("commission", 0))
                fee_by_asset = {asset: commission} if asset and commission else {}
                base_fee = fee_by_asset.get(self.base_asset, 0.0)
                quote_fee = fee_by_asset.get(self.quote_asset, 0.0)
                fee_usdt = base_fee * price + quote_fee
                fee_usdt_by_asset = {}
                if base_fee:
                    fee_usdt_by_asset[self.base_asset] = base_fee * price
                if quote_fee:
                    fee_usdt_by_asset[self.quote_asset] = quote_fee
                pnl = (price - self.average_entry_price) * qty - fee_usdt
                self.cash_usdt += quote - quote_fee
                self.realized_pnl_usdt += pnl
                self.fees_paid_usdt += fee_usdt
                self.base_quantity = max(0.0, self.base_quantity - qty - base_fee)
                if self.base_quantity < 1e-12:
                    self.base_quantity = 0.0
                    self.average_entry_price = 0.0
                self.trades.append({
                    "side": "sell", "price": price, "quantity": qty,
                    "notional_usdt": quote, "fee_usdt": fee_usdt,
                    "commission_by_asset": fee_by_asset,
                    "commission_usdt_by_asset": fee_usdt_by_asset,
                    "unpriced_commission_by_asset": {},
                    "accounting_complete": True, "fee_estimated": False,
                    "reason": "recovered_oco_fill", "timestamp": datetime.now(timezone.utc).isoformat(),
                    "exchange_order_id": int(fill.get("orderId", 0)),
                    "exchange_trade_id": trade_id, "exchange_order_list_id": list_id,
                    "status": "FILLED", "testnet": self.client.testnet,
                    "pnl_usdt": pnl,
                })
                self.processed_exchange_trade_ids.add(trade_id)
            self.processed_oco_list_ids.add(list_id)
            self.protective_order_list_id = None
            self.order_lists_reconciled = True
            return True
        except Exception:
            self.order_state_uncertain = True
            self.order_lists_reconciled = False
            log.exception("OCO offline recovery incomplete; blocking live actions (listId=%s)", list_id)
            return False

    def cancel_protective_oco(self) -> bool:
        """Cancel the protective order list and reconcile balances before market exit."""
        if not self.order_lists_reconciled:
            return False
        if self.protective_order_list_id is None:
            return True
        order_list_id = self.protective_order_list_id
        try:
            self.client.cancel_order_list(symbol=self.symbol, order_list_id=order_list_id)
        except Exception:
            log.exception("Could not cancel protective OCO listId=%s", order_list_id)
            try:
                self.sync_balances()
            except Exception:
                return False
            # If it remains open, never submit a competing market sell.
            return self.protective_order_list_id is None
        self.protective_order_list_id = None
        self.sync_balances()
        # A successful DELETE response is not enough: verify the exchange no
        # longer reports an active protective list before any competing exit.
        return self.protective_order_list_id is None

    def _min_notional(self) -> float:
        filters = self._load_filters()
        mn = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
        return float(mn.get("minNotional") or mn.get("notional") or 5.0)

    def buy(
        self, *, notional_usdt: float, price: float, reason: str,
        decision_mid: float | None = None,
    ) -> dict | None:
        if notional_usdt <= 0 or price <= 0:
            raise ValueError("Price and notional must be positive")
        if notional_usdt < self._min_notional():
            raise ValueError(f"Notional below exchange minimum ({self._min_notional()})")
        return self._place_market_order_once(
            side="BUY", reason=reason, quote_order_qty=notional_usdt, price=price,
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
        return self._place_market_order_once(
            side="SELL", reason=reason, quantity=qty, price=price,
            decision_mid=decision_mid if decision_mid is not None else price,
        )

    def attach_order_journal(self, store: PaperStore, key: str, *, verify_account: bool = False) -> None:
        if verify_account or isinstance(self.client, BinanceRestClient):
            uid = self.client.account().get("uid")
            if type(uid) is not int or uid <= 0:
                raise RuntimeError("Exchange did not identify the live account")
            store.bind_live_account(symbol=self.symbol, testnet=self.client.testnet, uid=uid)
        self._order_store = store
        self._order_store_key = key
        self._checkpoint_trade_count = len(self.trades)

    def _uncheckpointed_trades(self) -> list[tuple[str, dict[str, Any]]]:
        return [
            (live_trade_event_key(self, trade), trade)
            for trade in self.trades[self._checkpoint_trade_count:]
        ]

    def _mark_order_uncertain(self, client_id: str) -> None:
        self.order_state_machine.force_unknown(client_id)
        self.order_state_uncertain = True
        self.unresolved_client_order_id = client_id

    def _begin_order(self, *, side: str, kind: str, reason: str, **parameters: Any) -> dict:
        if self.order_state_uncertain:
            raise RuntimeError("Order state is uncertain; reconcile exchange orders before new orders")
        if self._order_store is None and isinstance(self.client, BinanceRestClient):
            raise RuntimeError("Live order submission requires a durable journal")
        client_id = "nq" + uuid4().hex
        intent = {
            "client_id": client_id, "symbol": self.symbol, "testnet": self.client.testnet,
            "side": side, "kind": kind, "reason": reason, **parameters,
        }
        self.order_state_machine.begin(client_id)
        self._order_sequence += 1
        # No POST, including a maker entry, can run until the intent has committed.
        if self._order_store is not None:
            try:
                self._order_store.begin_live_order(
                    self._order_store_key, intent, self.snapshot(), self._uncheckpointed_trades(),
                )
            except Exception:
                self._mark_order_uncertain(client_id)
                raise
            self._checkpoint_trade_count = len(self.trades)
        return intent

    def _validate_order_identity(self, intent: dict, result: OrderResult) -> None:
        exchange_id = intent.get("exchange_id")
        if (
            result.symbol != self.symbol or result.side != intent["side"] or result.order_id <= 0
            or (result.order_id != exchange_id if exchange_id else result.client_order_id != intent["client_id"])
        ):
            raise RuntimeError("Exchange order identity does not match durable intent")

    def _lookup_order(self, intent: dict) -> OrderResult:
        if intent.get("exchange_id"):
            return self.client.get_order(self.symbol, intent["exchange_id"])
        return self.client.get_order_by_client_id(self.symbol, intent["client_id"])

    def _checked_fills(self, result: OrderResult, *, recovering: bool) -> list[dict]:
        fills = list(result.fills or self.client.order_trades(self.symbol, result.order_id))
        if not fills:
            raise RuntimeError("Exchange fill history is not yet available")
        seen: set[int] = set()
        quantity = quote = 0.0
        for fill in fills:
            qty = float(fill["qty"])
            px = float(fill["price"])
            commission = float(fill["commission"])
            asset = str(fill.get("commissionAsset") or "").upper()
            trade_id = int(fill["tradeId"] if "tradeId" in fill else fill["id"])
            if (
                not all(math.isfinite(value) for value in (qty, px, commission))
                or qty <= 0 or px <= 0 or commission < 0 or not asset or trade_id < 0
                or trade_id in seen
                or ("orderId" in fill and int(fill["orderId"]) != result.order_id)
                or ("isBuyer" in fill and fill["isBuyer"] is not (result.side == "BUY"))
            ):
                raise RuntimeError("Invalid or duplicate exchange fill evidence")
            if recovering and commission and asset not in {self.base_asset, self.quote_asset}:
                raise RuntimeError("Recovered commission requires historical quote valuation")
            seen.add(trade_id)
            quantity += qty
            quote += qty * px
        if not (
            math.isclose(quantity, result.executed_qty, rel_tol=1e-9, abs_tol=1e-12)
            and math.isclose(quote, result.cummulative_quote_qty, rel_tol=1e-9, abs_tol=1e-8)
        ):
            raise RuntimeError("Exchange fill totals do not reconcile with terminal order")
        return fills

    def _settle_order(self, intent: dict, result: OrderResult, *, recovering: bool = False) -> dict | None:
        client_id = intent["client_id"]
        before = self.snapshot()
        trade_count = len(self.trades)
        try:
            self._validate_order_identity(intent, result)
            if result.status not in TERMINAL_ORDER_STATUSES:
                raise RuntimeError(f"Order {client_id} is not terminal ({result.status})")
            qty, quote = result.executed_qty, result.cummulative_quote_qty
            if (
                not all(math.isfinite(value) for value in (qty, quote))
                or qty < 0 or quote < 0 or (qty > 0) != (quote > 0)
                or (result.status == "FILLED" and qty <= 0)
                or (qty == 0 and result.fills)
            ):
                raise RuntimeError("Terminal order has invalid execution totals")
            trade = None
            if qty > 0:
                # Use the original ID even when Binance released it during cancellation.
                result = replace(result, client_order_id=client_id)
                if self._order_store is not None:
                    result = replace(result, fills=self._checked_fills(result, recovering=recovering))
                trade = self._apply_fill(
                    result, reason=intent["reason"], fallback_price=intent["price"],
                    decision_mid=intent["decision_mid"],
                )
                if self._order_store is not None and not trade["accounting_complete"]:
                    raise RuntimeError("Cannot finalize order without complete commission accounting")
            self.order_state_machine.observe(result.status)
            self.order_state_uncertain = False
            self.unresolved_client_order_id = None
            if self._order_store is not None:
                self._order_store.finish_live_order(
                    self._order_store_key, intent, self.snapshot(), self._uncheckpointed_trades(),
                    filled=trade is not None,
                )
                self._checkpoint_trade_count = len(self.trades)
            return trade
        except Exception:
            # A failed commit must not leave a partially-applied account in memory.
            del self.trades[trade_count:]
            before["trades"] = self.trades
            self.restore(before)
            self._mark_order_uncertain(client_id)
            raise

    def _place_market_order_once(
        self, *, side: str, reason: str,
        quantity: float | None = None, quote_order_qty: float | None = None,
        price: float = 0.0, decision_mid: float = 0.0,
    ) -> dict | None:
        """Submit once. A lost response only permits exchange lookup, never another POST."""
        with self._order_lock:
            intent = self._begin_order(
                side=side, kind="market", reason=reason, quantity=quantity,
                quote_order_qty=quote_order_qty, price=price, decision_mid=decision_mid,
            )
            client_id = intent["client_id"]
            order_started = time.perf_counter()
            try:
                try:
                    result = self.client.place_market_order(
                        symbol=self.symbol, side=side, quantity=quantity,
                        quote_order_qty=quote_order_qty, client_order_id=client_id,
                    )
                except Exception:
                    self._last_order_latency_measured = False
                    result = self._lookup_order(intent)
                else:
                    self._last_order_latency_measured = True
                self._last_order_latency_ms = (time.perf_counter() - order_started) * 1000.0
                return self._settle_order(intent, result)
            except Exception:
                self._mark_order_uncertain(client_id)
                raise

    def reconcile_uncertain_order(self) -> bool:
        """Resolve the durable intent after restart; require terminal, accounted evidence."""
        with self._order_lock:
            intent = self._order_store.pending_live_order() if self._order_store is not None else None
            if intent is None:
                return not (self.order_state_uncertain or (
                    self.order_state_machine.client_order_id and self.order_state_machine.blocks_new_orders
                ))
            client_id = intent["client_id"]
            self._mark_order_uncertain(client_id)
            if intent["symbol"] != self.symbol or intent["testnet"] is not self.client.testnet:
                return False
            try:
                order = self._lookup_order(intent)
                self._last_order_latency_ms = 0.0
                self._last_order_latency_measured = False
                self._settle_order(intent, order, recovering=True)
            except Exception:
                log.exception("Durable order %s remains unresolved; refusing further orders", client_id)
                return False
            return True

    def sell_all(self, *, price: float, reason: str = "manual_live_exit") -> dict | None:
        return self.sell_quantity(quantity=self.base_quantity, price=price, reason=reason)

    def _apply_fill(
        self, result: OrderResult, *, reason: str, fallback_price: float,
        decision_mid: float,
    ) -> dict:
        executed_qty = float(result.executed_qty)
        quote = float(result.cummulative_quote_qty)
        if executed_qty <= 0:
            raise RuntimeError(f"Order not filled: status={result.status} id={result.order_id}")

        fills = list(result.fills or [])
        if not fills:
            try:
                fills = self.client.order_trades(self.symbol, result.order_id)
            except Exception:
                log.warning("Actual commission fills unavailable for orderId=%s", result.order_id, exc_info=True)

        fee_by_asset: dict[str, float] = {}
        missing_commission_asset = False
        total_cost = 0.0
        total_qty = 0.0
        base_fee_usdt = 0.0
        for fill in fills:
            p = float(fill.get("price", 0))
            q = float(fill.get("qty", 0))
            if p > 0 and q > 0:
                total_cost += p * q
                total_qty += q
            asset = str(fill.get("commissionAsset", "")).upper()
            commission = float(fill.get("commission", 0))
            if commission > 0 and asset:
                fee_by_asset[asset] = fee_by_asset.get(asset, 0.0) + commission
                if asset == self.base_asset:
                    base_fee_usdt += commission * p
            elif commission > 0:
                missing_commission_asset = True

        if total_qty > 0:
            avg_price = total_cost / total_qty
            executed_qty = total_qty
            quote = total_cost
        else:
            avg_price = (quote / executed_qty) if executed_qty else fallback_price

        base_fee = fee_by_asset.get(self.base_asset, 0.0)
        quote_fee = fee_by_asset.get(self.quote_asset, 0.0)
        other_fees = {
            asset: amount for asset, amount in fee_by_asset.items()
            if asset not in (self.base_asset, self.quote_asset)
        }
        other_fee_usdt = 0.0
        fee_usdt_by_asset: dict[str, float] = {}
        if quote_fee:
            fee_usdt_by_asset[self.quote_asset] = quote_fee
        if base_fee:
            fee_usdt_by_asset[self.base_asset] = base_fee_usdt
        unpriced_fees: dict[str, float] = {}
        for asset, amount in other_fees.items():
            try:
                fee_price = float(self.client.ticker_price(f"{asset}{self.quote_asset}"))
                if not math.isfinite(fee_price) or fee_price <= 0:
                    raise ValueError("invalid commission conversion price")
                valued = amount * fee_price
                other_fee_usdt += valued
                fee_usdt_by_asset[asset] = valued
            except Exception as exc:
                unpriced_fees[asset] = amount
                log.error("Cannot value %s commission in %s: %s", asset, self.quote_asset, exc)
        fee_usdt = sum(fee_usdt_by_asset.values())
        accounting_complete = not unpriced_fees and not missing_commission_asset and bool(fills)
        fee_estimated = not fills
        if fee_estimated:
            fee_usdt = quote * self.fee_rate

        side = result.side.lower()
        trade: dict[str, Any] = {
            "side": side,
            "price": avg_price,
            "quantity": executed_qty,
            "notional_usdt": quote,
            "fee_usdt": fee_usdt,
            "commission_by_asset": fee_by_asset,
            "commission_usdt_by_asset": fee_usdt_by_asset,
            "other_fee_usdt": other_fee_usdt,
            "unpriced_commission_by_asset": unpriced_fees,
            "missing_commission_asset": missing_commission_asset,
            "accounting_complete": accounting_complete,
            "fee_estimated": fee_estimated,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "exchange_order_id": result.order_id,
            "client_order_id": result.client_order_id,
            "status": result.status,
            "testnet": self.client.testnet,
            "decision_mid": decision_mid,
            "execution_latency_ms": getattr(self, "_last_order_latency_ms", 0.0),
            "execution_latency_measured": getattr(self, "_last_order_latency_measured", False),
        }
        if side == "buy":
            # Stable exchange-derived ID makes OCO retries idempotent after a lost HTTP response.
            self.protective_order_client_id = f"nqoco{int(result.order_id):x}"[:36]
            net_base = max(0.0, executed_qty - base_fee)
            old_cost = self.base_quantity * self.average_entry_price
            self.base_quantity += net_base
            self.average_entry_price = (
                (old_cost + quote + quote_fee + other_fee_usdt) / self.base_quantity
                if self.base_quantity else 0.0
            )
            self.cash_usdt = max(0.0, self.cash_usdt - quote - quote_fee)
            self.fees_paid_usdt += fee_usdt
        else:
            pnl = (avg_price - self.average_entry_price) * executed_qty - fee_usdt
            self.cash_usdt += quote - quote_fee
            self.fees_paid_usdt += fee_usdt
            # Do not publish or learn from a partial PnL when a commission asset
            # could not be valued in quote currency.
            if accounting_complete:
                self.realized_pnl_usdt += pnl
                trade["pnl_usdt"] = pnl
            else:
                trade["pnl_usdt"] = None
            self.base_quantity = max(0.0, self.base_quantity - executed_qty - base_fee)
            if self.base_quantity < 1e-12:
                self.base_quantity = 0.0
                self.average_entry_price = 0.0
        self.trades.append(trade)
        log.info(
            "LIVE %s filled qty=%.8f price=%.4f notional=%.4f fee=%.6f "
            "orderId=%s status=%s testnet=%s accounting_complete=%s",
            side.upper(), executed_qty, avg_price, quote, fee_usdt,
            result.order_id, result.status, self.client.testnet, accounting_complete,
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
            "last_order_latency_ms": getattr(self, "_last_order_latency_ms", 0.0),
            "last_order_latency_measured": getattr(self, "_last_order_latency_measured", False),
            "order_state_uncertain": self.order_state_uncertain,
            "unresolved_client_order_id": self.unresolved_client_order_id,
            "order_state_machine": self.order_state_machine.snapshot(),
            "processed_exchange_trade_ids": sorted(self.processed_exchange_trade_ids),
            "processed_oco_list_ids": sorted(self.processed_oco_list_ids),
            "locked_base_quantity": self.locked_base_quantity,
            "locked_quote_balance": self.locked_quote_balance,
            "open_orders_count": len(self.open_orders_snapshot),
            "open_order_lists_count": len(self.open_order_lists_snapshot),
            "protective_order_list_id": self.protective_order_list_id,
            "protective_order_client_id": self.protective_order_client_id,
            "order_lists_reconciled": self.order_lists_reconciled,
            "mode": "live",
            "testnet": self.client.testnet,
        }
