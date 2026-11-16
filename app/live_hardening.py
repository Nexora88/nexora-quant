"""Runtime hardening for LiveExecutor: OCO retries + emergency flatten.

After a live BUY fill, exchange-hosted OCO protection must be reconciled promptly.
Ambiguous POST outcomes are looked up by stable client ID before retrying. A market
flatten is permitted only when the exchange confirms no active OCO; uncertain order
state blocks competing orders and requires operator reconciliation.
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

log = logging.getLogger(__name__)


def harden_live_executor() -> None:
    from app import live as live_mod

    LiveExecutor = live_mod.LiveExecutor
    if getattr(LiveExecutor, "_nexora_hardened", False):
        return

    _orig_init = LiveExecutor.__init__

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _orig_init(self, *args, **kwargs)
        if not hasattr(self, "emergency"):
            self.emergency = False
            self.emergency_reason = None

    def _oco_not_found(exc: Exception) -> bool:
        body = str(getattr(exc, "binance_body", "")) + " " + str(exc)
        return "-2013" in body or "Order does not exist" in body

    def ensure_protective_oco(
        self,
        *,
        current_price: float,
        take_profit_pct: float,
        stop_loss_pct: float,
        retries: int = 3,
        retry_delay_s: float = 0.25,
    ) -> bool:
        """Install exchange-hosted OCO with a stable client ID and reconcile ambiguous replies."""
        if current_price <= 0 or not 0 < take_profit_pct < 100 or not 0 < stop_loss_pct < 100:
            return False
        if getattr(self, "order_state_uncertain", False):
            return False
        if getattr(self, "protective_order_list_id", None) is not None:
            return True

        client_id = getattr(self, "protective_order_client_id", None)
        if not client_id:
            last_buy = next((t for t in reversed(self.trades) if t.get("side") == "buy"), None)
            identity = str((last_buy or {}).get("exchange_order_id") or
                           f"{self.symbol}|{self.base_quantity:.12f}|{self.average_entry_price:.12f}")
            client_id = "nqoco" + hashlib.sha256(identity.encode()).hexdigest()[:20]
            self.protective_order_client_id = client_id

        def resolve_existing() -> bool | None:
            nonlocal client_id
            lookup = getattr(self.client, "get_order_list_by_client_id", None)
            if not callable(lookup):
                self.order_state_uncertain = True
                self.unresolved_client_order_id = client_id
                return False
            try:
                detail = lookup(self.symbol, client_id)
            except Exception as exc:
                if _oco_not_found(exc):
                    return None
                self.order_state_uncertain = True
                self.unresolved_client_order_id = client_id
                log.exception("OCO submission state is ambiguous; blocking all further orders")
                return False
            status = str(detail.get("listStatusType", ""))
            list_id = int(detail.get("orderListId") or 0)
            if list_id <= 0:
                self.order_state_uncertain = True
                self.unresolved_client_order_id = client_id
                return False
            if status in {"EXEC_STARTED", "EXECUTING"}:
                self.protective_order_list_id = list_id
                self.order_lists_reconciled = True
                return True
            if status not in {"ALL_DONE", "REJECT", "EXPIRED"}:
                self.order_state_uncertain = True
                self.unresolved_client_order_id = client_id
                log.error("Unknown OCO list status=%s; blocking market orders", status)
                return False
            # A terminal list may have filled while the response was lost.
            self.protective_order_list_id = list_id
            if not self.reconcile_protective_oco():
                self.order_state_uncertain = True
                self.unresolved_client_order_id = client_id
                return False
            if self.base_quantity <= 1e-12:
                return True
            # A terminal list may have been cancelled or only partially filled.
            # Reconcile its fills, then protect the remaining position with a new ID.
            rotated = hashlib.sha256(
                f"{client_id}|{list_id}|{self.base_quantity:.12f}".encode()
            ).hexdigest()[:20]
            client_id = "nqoco" + rotated
            self.protective_order_client_id = client_id
            return None

        existing = resolve_existing()
        if existing is not None:
            return existing

        last_err: Exception | None = None
        for attempt in range(1, max(1, retries) + 1):
            try:
                available = self._round_step(self.client.free_balance(self.base_asset))
                if available <= 0:
                    return self.base_quantity <= 1e-12
                take_profit = self._round_price(
                    self.average_entry_price * (1 + take_profit_pct / 100), round_up=True,
                )
                stop_price = self._round_price(
                    self.average_entry_price * (1 - stop_loss_pct / 100), round_up=False,
                )
                if take_profit <= current_price or stop_price >= current_price or stop_price <= 0:
                    log.error("OCO prices invalid relative to current market")
                    return False
                response = self.client.place_oco_order(
                    symbol=self.symbol, side="SELL", quantity=available,
                    take_profit_price=take_profit, stop_price=stop_price,
                    stop_limit_price=self._round_price(stop_price * 0.999, round_up=False),
                    client_order_id=client_id, stop_loss_market=True,
                )
                list_id = int(response.get("orderListId") or response.get("orderListID") or 0)
                status = str(response.get("listStatusType") or "")
                if list_id > 0 and status in {"EXEC_STARTED", "EXECUTING"}:
                    self.protective_order_list_id = list_id
                    self.order_lists_reconciled = True
                    log.info("OCO installed list_id=%s attempt=%s", list_id, attempt)
                    return True
                if list_id > 0 and status in {"ALL_DONE", "REJECT", "EXPIRED"}:
                    self.protective_order_list_id = list_id
                    if not self.reconcile_protective_oco():
                        self.order_state_uncertain = True
                        self.unresolved_client_order_id = client_id
                        return False
                    if self.base_quantity <= 1e-12:
                        return True
                    rotated = hashlib.sha256(
                        f"{client_id}|{list_id}|{self.base_quantity:.12f}".encode()
                    ).hexdigest()[:20]
                    client_id = "nqoco" + rotated
                    self.protective_order_client_id = client_id
                    last_err = RuntimeError("OCO became terminal before protection was confirmed")
                else:
                    last_err = RuntimeError("OCO response missing ID or has unknown list status")
                    resolved = resolve_existing()
                    if resolved is not None:
                        return resolved
            except Exception as exc:
                last_err = exc
                log.warning("OCO install failed attempt=%s/%s: %s", attempt, retries, exc)
                resolved = resolve_existing()
                if resolved is not None:
                    return resolved
            if attempt < retries:
                time.sleep(retry_delay_s * attempt)
        if last_err is not None:
            log.error("OCO install failed after %s retries: %s", retries, last_err)
        return False

    def emergency_flatten(self, *, reason: str = "oco_failed", mark_price: float = 0.0):
        """Flatten only after exchange confirms that protective OCO is cancelled."""
        self.emergency = True
        self.emergency_reason = reason
        try:
            if getattr(self, "order_state_uncertain", False):
                raise RuntimeError("Exchange order state is uncertain; refusing competing market exit")
            if getattr(self, "protective_order_list_id", None) is not None:
                if not self.cancel_protective_oco():
                    raise RuntimeError("Protective OCO cancellation was not confirmed; refusing market exit")
            px = float(mark_price) if mark_price and mark_price > 0 else float(self.average_entry_price or 0)
            if px <= 0:
                raise RuntimeError("Cannot emergency flatten without a valid mark price")
            trade = self.sell_all(price=px, reason=f"EMERGENCY_FLATTEN:{reason}")
            log.critical("EMERGENCY flatten reason=%s trade=%s", reason, trade)
            return trade
        except Exception:
            log.exception("EMERGENCY flatten blocked reason=%s", reason)
            self.order_state_uncertain = True
            return None

    def install_protection_or_flatten(
        self,
        *,
        current_price: float,
        take_profit_pct: float,
        stop_loss_pct: float,
        mark_price: float | None = None,
    ) -> bool:
        """After BUY: install OCO or immediately flatten. Never leave a naked long."""
        ok = self.ensure_protective_oco(
            current_price=current_price,
            take_profit_pct=take_profit_pct,
            stop_loss_pct=stop_loss_pct,
            retries=3,
            retry_delay_s=0.25,
        )
        if ok:
            return True
        self.emergency_flatten(
            reason="oco_install_failed",
            mark_price=float(mark_price or current_price or 0),
        )
        return False

    LiveExecutor.__init__ = __init__  # type: ignore[method-assign]
    LiveExecutor.install_protection_or_flatten = install_protection_or_flatten  # type: ignore[method-assign]
    LiveExecutor.ensure_protective_oco = ensure_protective_oco  # type: ignore[method-assign]
    LiveExecutor.emergency_flatten = emergency_flatten  # type: ignore[method-assign]
    LiveExecutor._nexora_hardened = True  # type: ignore[attr-defined]
    log.info("LiveExecutor OCO retry + emergency flatten hardening applied")
