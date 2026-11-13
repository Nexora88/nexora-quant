"""Post-only LIMIT_MAKER entry for LiveExecutor."""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)


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
    """Post-only LIMIT_MAKER entry. Poll briefly; cancel residual if unfilled."""
    if notional_usdt <= 0 or limit_price <= 0:
        raise ValueError("Price and notional must be positive")
    if notional_usdt < self._min_notional():
        raise ValueError(f"Notional below exchange minimum ({self._min_notional()})")
    qty = self._round_step(notional_usdt / limit_price)
    if qty <= 0:
        return None
    limit_price = self._round_price(limit_price, round_up=False)
    with self._order_lock:
        if self.order_state_uncertain:
            raise RuntimeError(
                "Order state is uncertain; reconcile exchange orders before new orders"
            )
        client_id = f"nqlm{time.time_ns():x}"[:36]
        try:
            result = self.client.place_limit_order(
                symbol=self.symbol,
                side="BUY",
                quantity=qty,
                price=limit_price,
                client_order_id=client_id,
                post_only=post_only,
            )
        except Exception:
            log.exception("LIMIT_MAKER place failed")
            raise
        deadline = time.time() + max(0.5, float(wait_seconds))
        last = result
        while time.time() < deadline:
            if last.status in {"FILLED", "PARTIALLY_FILLED"} and last.executed_qty > 0:
                break
            if last.status in {"CANCELED", "EXPIRED", "REJECTED"}:
                break
            time.sleep(0.35)
            try:
                last = self.client.get_order(self.symbol, last.order_id)
            except Exception:
                log.exception("poll limit order failed")
                break
        if last.executed_qty <= 0 or last.status not in {"FILLED", "PARTIALLY_FILLED"}:
            try:
                self.client.cancel_order(symbol=self.symbol, order_id=last.order_id)
            except Exception:
                log.exception("cancel unfilled limit order failed")
            return None
        if last.status == "PARTIALLY_FILLED":
            try:
                self.client.cancel_order(symbol=self.symbol, order_id=last.order_id)
            except Exception:
                log.exception("cancel residual limit order failed")
        return self._apply_fill(
            last,
            reason=f"{reason};limit_maker",
            fallback_price=limit_price,
            decision_mid=decision_mid if decision_mid is not None else limit_price,
        )


def install_buy_limit(LiveExecutor: type) -> None:
    if not hasattr(LiveExecutor, "buy_limit"):
        LiveExecutor.buy_limit = _buy_limit  # type: ignore[attr-defined]
