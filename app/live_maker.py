"""Post-only LIMIT_MAKER entry for LiveExecutor."""
from __future__ import annotations

import logging
import time

from app.live import TERMINAL_ORDER_STATUSES

log = logging.getLogger(__name__)


def _maker_metric(name: str) -> None:
    try:
        from app.engine_setup import state
        attr = f"maker_entry_{name}"
        setattr(state, attr, int(getattr(state, attr, 0) or 0) + 1)
    except Exception:
        log.exception("Could not record maker execution metric: %s", name)


def _buy_limit(
    self,
    *,
    notional_usdt: float,
    limit_price: float,
    reason: str,
    decision_mid: float | None = None,
    wait_seconds: float = 8.0,
    post_only: bool = True,
):
    """Post-only LIMIT_MAKER entry. Poll briefly; cancel residual if unfilled.

    A partial fill is not applied until terminal exchange state is verified.
    """
    if notional_usdt <= 0 or limit_price <= 0:
        raise ValueError("Price and notional must be positive")
    if notional_usdt < self._min_notional():
        raise ValueError(f"Notional below exchange minimum ({self._min_notional()})")
    # Round price first so qty/notional edge cases use exchange tick.
    limit_price = self._round_price(float(limit_price), round_up=False)
    if limit_price <= 0:
        return None
    qty = self._round_step(notional_usdt / limit_price)
    if qty <= 0:
        return None
    # Re-check min notional after rounding (qty * price may undershoot).
    if qty * limit_price < self._min_notional() * 0.999:
        return None
    with self._order_lock:
        _maker_metric("attempts")
        intent = self._begin_order(
            side="BUY", kind="limit_maker" if post_only else "limit",
            reason=f"{reason};limit_maker", quantity=qty, price=limit_price,
            decision_mid=decision_mid if decision_mid is not None else limit_price,
        )
        started = time.perf_counter()
        self._last_order_latency_measured = False  # POST RTT alone isn't time to maker fill
        try:
            try:
                last = self.client.place_limit_order(
                    symbol=self.symbol, side="BUY", quantity=qty, price=limit_price,
                    client_order_id=intent["client_id"], post_only=post_only,
                )
            except Exception:
                last = self._lookup_order(intent)
            self._validate_order_identity(intent, last)
            if last.status not in TERMINAL_ORDER_STATUSES:
                if self._order_store is not None:
                    intent = self._order_store.identify_live_order(intent, last.order_id)
                else:
                    intent = {**intent, "exchange_id": last.order_id}
                deadline = time.monotonic() + max(0.5, float(wait_seconds))
                while last.status in {"NEW", "PENDING_NEW"} and time.monotonic() < deadline:
                    time.sleep(min(0.35, max(0.0, deadline - time.monotonic())))
                    try:
                        last = self._lookup_order(intent)
                    except Exception:
                        log.warning("Maker polling failed; attempting to cancel the known order", exc_info=True)
                        break
                    self._validate_order_identity(intent, last)
                if last.status not in TERMINAL_ORDER_STATUSES:
                    if time.monotonic() >= deadline:
                        _maker_metric("timeouts")
                    try:
                        self.client.cancel_order(symbol=self.symbol, order_id=intent["exchange_id"])
                    except Exception:
                        log.warning("Maker cancel response unavailable; verifying terminal status", exc_info=True)
                    # Neither a cancel ACK nor the last pre-cancel partial is settlement evidence.
                    last = self._lookup_order(intent)
            self._last_order_latency_ms = (time.perf_counter() - started) * 1000.0
            trade = self._settle_order(intent, last)
            if trade is not None:
                _maker_metric("fills")
            return trade
        except Exception:
            self._mark_order_uncertain(intent["client_id"])
            raise


def install_buy_limit(LiveExecutor: type) -> None:
    if not hasattr(LiveExecutor, "buy_limit"):
        LiveExecutor.buy_limit = _buy_limit  # type: ignore[attr-defined]


# Back-compat alias used by older engine_setup snippets
install_maker_entry = install_buy_limit
