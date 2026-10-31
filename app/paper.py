"""Paper executor with explicit snapshot/restore support; never contacts an exchange."""
from datetime import datetime, timezone
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
        self.realized_pnl_usdt = 0.0
        self.fees_paid_usdt = 0.0
        self.trades: list[dict[str, Any]] = []

    def restore(self, snapshot: dict[str, Any]) -> None:
        """Restore a previously saved account after validating numeric invariants."""
        numeric = ("starting_cash_usdt", "cash_usdt", "base_quantity",
                   "average_entry_price", "realized_pnl_usdt", "fees_paid_usdt")
        values = {key: float(snapshot[key]) for key in numeric}
        if any(value != value or abs(value) == float("inf") for value in values.values()):
            raise ValueError("Paper snapshot contains non-finite values")
        if values["starting_cash_usdt"] <= 0 or values["cash_usdt"] < -1e-8:
            raise ValueError("Paper snapshot has invalid cash")
        if values["base_quantity"] < 0 or values["average_entry_price"] < 0:
            raise ValueError("Paper snapshot has invalid position")
        if (values["base_quantity"] > 0) != (values["average_entry_price"] > 0):
            raise ValueError("Paper snapshot position and entry price are inconsistent")
        self.starting_cash_usdt = values["starting_cash_usdt"]
        self.cash_usdt = values["cash_usdt"]
        self.base_quantity = values["base_quantity"]
        self.average_entry_price = values["average_entry_price"]
        if self.base_quantity < 1e-12:
            self.base_quantity = 0.0
            self.average_entry_price = 0.0
        self.realized_pnl_usdt = values["realized_pnl_usdt"]
        self.fees_paid_usdt = values["fees_paid_usdt"]
        self.trades = list(snapshot.get("trades", []))

    def buy(self, *, notional_usdt: float, price: float, reason: str) -> dict:
        if price <= 0 or notional_usdt <= 0:
            raise ValueError("Price and notional must be positive")
        fee = notional_usdt * self.fee_rate
        total = notional_usdt + fee
        if total > self.cash_usdt + 1e-9:
            raise ValueError("Insufficient paper cash")
        quantity = notional_usdt / price
        old_cost = self.base_quantity * self.average_entry_price
        self.base_quantity += quantity
        self.average_entry_price = (old_cost + notional_usdt) / self.base_quantity
        self.cash_usdt -= total
        self.fees_paid_usdt += fee
        trade = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "side": "buy",
            "quantity": quantity,
            "price": price,
            "notional_usdt": notional_usdt,
            "fee_usdt": fee,
            "pnl_usdt": 0.0,
            "reason": reason,
            "accounting_complete": True,
        }
        self.trades.append(trade)
        return trade

    def sell_quantity(self, *, quantity: float, price: float, reason: str) -> dict:
        if price <= 0 or quantity <= 0:
            raise ValueError("Price and quantity must be positive")
        if self.base_quantity <= 0:
            raise ValueError("No paper position to sell")
        quantity = min(quantity, self.base_quantity)
        notional = quantity * price
        fee = notional * self.fee_rate
        pnl = (price - self.average_entry_price) * quantity - fee
        self.cash_usdt += notional - fee
        self.fees_paid_usdt += fee
        self.realized_pnl_usdt += pnl
        self.base_quantity = max(0.0, self.base_quantity - quantity)
        if self.base_quantity < 1e-12:
            self.base_quantity = 0.0
            self.average_entry_price = 0.0
        trade = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "side": "sell",
            "quantity": quantity,
            "price": price,
            "notional_usdt": notional,
            "fee_usdt": fee,
            "pnl_usdt": pnl,
            "reason": reason,
            "accounting_complete": True,
        }
        self.trades.append(trade)
        return trade

    def sell_all(self, *, price: float, reason: str) -> dict:
        return self.sell_quantity(quantity=self.base_quantity, price=price, reason=reason)

    def snapshot(self, mark: float | None = None) -> dict[str, Any]:
        mark = float(mark or self.average_entry_price or 0.0)
        market_value = self.base_quantity * mark
        unrealized = (mark - self.average_entry_price) * self.base_quantity if self.base_quantity and mark else 0.0
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
            "trades": list(self.trades[-20:]),
        }
