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
        self.starting_cash_usdt = values["starting_cash_usdt"]
        self.cash_usdt = values["cash_usdt"]
        self.base_quantity = values["base_quantity"]
        self.average_entry_price = values["average_entry_price"]
        self.realized_pnl_usdt = values["realized_pnl_usdt"]
        self.fees_paid_usdt = values["fees_paid_usdt"]
        self.trades = list(snapshot.get("trades", []))

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
        self.cash_usdt -= notional_usdt + fee
        self.fees_paid_usdt += fee
        trade = {"side": "buy", "price": price, "quantity": quantity,
                 "notional_usdt": notional_usdt, "fee_usdt": fee, "reason": reason,
                 "timestamp": datetime.now(timezone.utc).isoformat()}
        self.trades.append(trade)
        return trade

    def sell_all(self, *, price: float, reason: str = "manual_paper_exit") -> dict | None:
        if price <= 0:
            raise ValueError("Price must be positive")
        if self.base_quantity <= 0:
            return None
        quantity = self.base_quantity
        gross = quantity * price
        fee = gross * self.fee_rate
        pnl = (price - self.average_entry_price) * quantity - fee
        self.cash_usdt += gross - fee
        self.realized_pnl_usdt += pnl
        self.fees_paid_usdt += fee
        trade = {"side": "sell", "price": price, "quantity": quantity,
                 "notional_usdt": gross, "fee_usdt": fee, "pnl_usdt": pnl,
                 "reason": reason, "timestamp": datetime.now(timezone.utc).isoformat()}
        self.trades.append(trade)
        self.base_quantity = 0.0
        self.average_entry_price = 0.0
        return trade

    def snapshot(self, mark_price: float | None = None) -> dict:
        mark = mark_price or self.average_entry_price
        market_value = self.base_quantity * mark
        unrealized = (mark - self.average_entry_price) * self.base_quantity if self.base_quantity and mark else 0.0
        return {"starting_cash_usdt": self.starting_cash_usdt, "cash_usdt": self.cash_usdt,
                "base_quantity": self.base_quantity, "average_entry_price": self.average_entry_price,
                "market_value_usdt": market_value, "equity_usdt": self.cash_usdt + market_value,
                "unrealized_pnl_usdt": unrealized, "realized_pnl_usdt": self.realized_pnl_usdt,
                "fees_paid_usdt": self.fees_paid_usdt, "trade_count": len(self.trades),
                "trades": self.trades[-100:]}
