"""Runtime hardening for LiveExecutor: OCO retries + emergency flatten."""
from __future__ import annotations

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

    def ensure_protective_oco(
        self,
        *,
        current_price: float,
        take_profit_pct: float,
        stop_loss_pct: float,
        retries: int = 3,
        retry_delay_s: float = 0.35,
    ) -> bool:
        if current_price <= 0 or not 0 < take_profit_pct < 100 or not 0 < stop_loss_pct < 100:
            return False
        if getattr(self, "order_state_uncertain", False):
            return False
        if getattr(self, "protective_order_list_id", None) is not None:
            return True
        last_err: Exception | None = None
        for attempt in range(1, max(1, retries) + 1):
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
                    log.error("OCO prices invalid relative to current market")
                    return False
                response = self.client.place_oco_order(
                    symbol=self.symbol,
                    side="SELL",
                    quantity=available,
                    take_profit_price=take_profit,
                    stop_price=stop_price,
                    stop_limit_price=stop_limit,
                    client_order_id=f"nqoco{time.time_ns():x}"[:36],
                )
                list_id = int(response.get("orderListId", 0)) or None
                self.protective_order_list_id = list_id
                if hasattr(self, "open_order_lists_snapshot"):
                    self.open_order_lists_snapshot.append(response)
                if list_id is not None:
                    self._order_sequence = getattr(self, "_order_sequence", 0) + 1
                    log.info("Exchange OCO installed listId=%s attempt=%s", list_id, attempt)
                    return True
            except Exception as exc:
                last_err = exc
                log.warning("OCO install failed attempt=%s/%s: %s", attempt, retries, exc)
            if attempt < retries:
                time.sleep(retry_delay_s * attempt)
        if last_err is not None:
            log.error("OCO install failed after %s retries: %s", retries, last_err)
        return False

    def emergency_flatten(self, *, reason: str = "oco_failed", mark_price: float = 0.0):
        self.emergency = True
        self.emergency_reason = reason
        try:
            if getattr(self, "protective_order_list_id", None) is not None:
                try:
                    self.cancel_protective_oco()
                except Exception:
                    log.exception("Emergency: cancel OCO failed")
            px = float(mark_price) if mark_price and mark_price > 0 else float(self.average_entry_price or 0)
            if px <= 0:
                px = 1e-8
            trade = self.sell_all(price=px, reason=f"EMERGENCY_FLATTEN:{reason}")
            log.critical("EMERGENCY flatten reason=%s trade=%s", reason, trade)
            return trade
        except Exception:
            log.exception("EMERGENCY flatten failed reason=%s", reason)
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
        ok = self.ensure_protective_oco(
            current_price=current_price,
            take_profit_pct=take_profit_pct,
            stop_loss_pct=stop_loss_pct,
            retries=3,
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
