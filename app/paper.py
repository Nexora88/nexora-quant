"""Paper executor with explicit snapshot/restore support; never contacts an exchange."""
from datetime import datetime, timezone
from math import isfinite, isclose
from typing import Any


class PaperExecutor:
    def __init__(self, starting_cash_usdt: float, fee_rate: float) -> None:
        if starting_cash_usdt <= 0 or not 0 <= fee_rate < 0.1:
            raise ValueError("Invalid paper account settings")
        self.starting_cash_usdt = starting_cash_usdt
        self.cash_usdt = starting_cash_usdt
        self.fee_rate = fee_rate
        self.base_quantity = 0.0
        self.average_entry_price = 0.0
        self.entry_fees_remaining_usdt = 0.0
        self.realized_pnl_usdt = 0.0
        self.fees_paid_usdt = 0.0
        self.trades: list[dict[str, Any]] = []

    def restore(self, snapshot: dict[str, Any]) -> None:
        """Restore a previously saved account after validating numeric invariants."""
        numeric = (
            "starting_cash_usdt", "cash_usdt", "base_quantity",
            "average_entry_price", "realized_pnl_usdt", "fees_paid_usdt",
        )
        values = {key: float(snapshot[key]) for key in numeric}
        trades = list(snapshot.get("trades", []))
        if "entry_fees_remaining_usdt" in snapshot:
            entry_fees = float(snapshot["entry_fees_remaining_usdt"])
        elif values["base_quantity"] > 1e-12:
            # Migrate legacy snapshots only when the retained trade history can
            # exactly explain the currently open quantity and its remaining fees.
            remaining_qty = 0.0
            remaining_fees = 0.0
            for trade in trades:
                side = str(trade.get("side", "")).lower()
                quantity = float(trade.get("quantity") or 0.0)
                if side == "buy":
                    if "fee_usdt" not in trade:
                        raise ValueError("legacy paper ledger lacks historical buy fee data")
                    remaining_qty += quantity
                    remaining_fees += float(trade["fee_usdt"])
                elif side == "sell" and remaining_qty > 0:
                    sold = min(quantity, remaining_qty)
                    allocated = remaining_fees * sold / remaining_qty
                    remaining_qty -= sold
                    remaining_fees = max(0.0, remaining_fees - allocated)
            if not isclose(remaining_qty, values["base_quantity"], rel_tol=1e-6, abs_tol=1e-10):
                raise ValueError(
                    "legacy paper position cost/fee history is incomplete; refusing inaccurate restore"
                )
            entry_fees = remaining_fees
        else:
            entry_fees = 0.0

        if any(not isfinite(value) for value in (*values.values(), entry_fees)):
            raise ValueError("Paper snapshot contains non-finite values")
        if values["starting_cash_usdt"] <= 0 or values["cash_usdt"] < -1e-8:
            raise ValueError("Paper snapshot has invalid cash")
        if values["base_quantity"] < 0 or values["average_entry_price"] < 0 or entry_fees < 0:
            raise ValueError("Paper snapshot has invalid position or entry fees")
        if (values["base_quantity"] > 0) != (values["average_entry_price"] > 0):
            raise ValueError("Paper snapshot position and entry price are inconsistent")
        self.starting_cash_usdt = values["starting_cash_usdt"]
        self.cash_usdt = values["cash_usdt"]
        self.base_quantity = values["base_quantity"]
        self.average_entry_price = values["average_entry_price"]
        self.entry_fees_remaining_usdt = entry_fees
        if self.base_quantity < 1e-12:
            self.base_quantity = 0.0
            self.average_entry_price = 0.0
            self.entry_fees_remaining_usdt = 0.0
        self.realized_pnl_usdt = values["realized_pnl_usdt"]
        self.fees_paid_usdt = values["fees_paid_usdt"]
        self.trades = trades

    def buy(self, *, notional_usdt: float, price: float, reason: str) -> dict:
        if price <= 0 or notional_usdt <= 0:
            raise ValueError("Price and notional must be positive")
        fee = notional_usdt * self.fee_rate
        if notional_usdt + fee > self.cash_usdt:
            raise ValueError("Insufficient paper cash including fee")
        quantity = notional_usdt / price
        old_cost = self.base_quantity * self.average_entry_price
        self.base_quantity += quantity
        self.average_entry_price = (old_cost + notional_usdt) / self.base_quantity
        self.entry_fees_remaining_usdt += fee
        self.cash_usdt -= notional_usdt + fee
        self.fees_paid_usdt += fee
        trade = {
            "side": "buy",
            "price": price,
            "quantity": quantity,
            "notional_usdt": notional_usdt,
            "fee_usdt": fee,
            "pnl_usdt": 0.0,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "accounting_complete": True,
        }
        self.trades.append(trade)
        return trade

    def sell_quantity(self, *, quantity: float, price: float, reason: str) -> dict | None:
        """Sell a simulated partial quantity and allocate its entry fee pro rata."""
        if price <= 0 or quantity <= 0:
            raise ValueError("Price and quantity must be positive")
        if self.base_quantity <= 0:
            return None
        quantity = min(quantity, self.base_quantity)
        prior_quantity = self.base_quantity
        gross = quantity * price
        fee = gross * self.fee_rate
        allocated_entry_fee = self.entry_fees_remaining_usdt * quantity / prior_quantity
        pnl = (price - self.average_entry_price) * quantity - fee - allocated_entry_fee
        self.cash_usdt += gross - fee
        self.realized_pnl_usdt += pnl
        self.fees_paid_usdt += fee
        self.entry_fees_remaining_usdt = max(0.0, self.entry_fees_remaining_usdt - allocated_entry_fee)
        trade = {
            "side": "sell",
            "price": price,
            "quantity": quantity,
            "notional_usdt": gross,
            "fee_usdt": fee,
            "entry_fee_allocated_usdt": allocated_entry_fee,
            "pnl_usdt": pnl,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "accounting_complete": True,
        }
        self.trades.append(trade)
        self.base_quantity = max(0.0, self.base_quantity - quantity)
        if self.base_quantity < 1e-12:
            self.base_quantity = 0.0
            self.average_entry_price = 0.0
            self.entry_fees_remaining_usdt = 0.0
        return trade

    def sell_all(self, *, price: float, reason: str = "manual_paper_exit") -> dict | None:
        return self.sell_quantity(quantity=self.base_quantity, price=price, reason=reason)

    def snapshot(self, mark_price: float | None = None) -> dict:
        mark = mark_price or self.average_entry_price
        market_value = self.base_quantity * mark
        unrealized = (
            (mark - self.average_entry_price) * self.base_quantity - self.entry_fees_remaining_usdt
            if self.base_quantity and mark
            else 0.0
        )
        return {
            "starting_cash_usdt": self.starting_cash_usdt,
            "cash_usdt": self.cash_usdt,
            "base_quantity": self.base_quantity,
            "average_entry_price": self.average_entry_price,
            "entry_fees_remaining_usdt": self.entry_fees_remaining_usdt,
            "market_value_usdt": market_value,
            "equity_usdt": self.cash_usdt + market_value,
            "unrealized_pnl_usdt": unrealized,
            "realized_pnl_usdt": self.realized_pnl_usdt,
            "fees_paid_usdt": self.fees_paid_usdt,
            "trade_count": len(self.trades),
            "trades": self.trades[-100:],
        }

def restore_paper_account(
    executor: PaperExecutor,
    snapshot: dict[str, Any],
    *,
    resume_position: bool = True,
) -> bool:
    """Restore the ledger without rebasing cash or silently discarding positions."""
    executor.restore(snapshot)
    has_position = float(executor.base_quantity) > 1e-12
    if has_position and not resume_position:
        raise RuntimeError(
            "A paper position is open in the saved ledger; refusing to discard it"
        )
    return has_position
