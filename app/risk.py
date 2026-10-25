"""Central pre-trade risk gate for simulated orders."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RiskDecision:
    allowed: bool
    reason: str


class RiskManager:
    def __init__(self, *, max_order_size_usdt: float, max_daily_loss_usdt: float,
                 max_consecutive_losses: int, max_spread_bps: float,
                 max_data_age_seconds: float) -> None:
        self.max_order_size_usdt = max_order_size_usdt
        self.max_daily_loss_usdt = max_daily_loss_usdt
        self.max_consecutive_losses = max_consecutive_losses
        self.max_spread_bps = max_spread_bps
        self.max_data_age_seconds = max_data_age_seconds
        self.realized_pnl_today = 0.0
        self.consecutive_losses = 0
        self.kill_switch = False
        self.kill_switch_reason = None
        self.day_utc: str | None = None

    def rollover_day(self, day_utc: str) -> bool:
        """Reset only the daily counter at UTC date change; preserve other risk brakes."""
        if self.day_utc == day_utc:
            return False
        self.day_utc = day_utc
        self.realized_pnl_today = 0.0
        if self.kill_switch_reason == "Daily simulated loss limit reached":
            self.kill_switch = False
            self.kill_switch_reason = None
        return True

    def evaluate_entry(self, *, notional_usdt: float, available_cash: float,
                       bid: float, ask: float, data_age_seconds: float | None) -> RiskDecision:
        if self.kill_switch:
            return RiskDecision(False, self.kill_switch_reason or "Kill switch active")
        if notional_usdt <= 0:
            return RiskDecision(False, "Order notional must be positive")
        if notional_usdt > self.max_order_size_usdt:
            return RiskDecision(False, "Order exceeds configured maximum")
        if notional_usdt > available_cash:
            return RiskDecision(False, "Insufficient paper cash")
        if bid <= 0 or ask <= 0 or ask < bid:
            return RiskDecision(False, "Invalid bid/ask market")
        spread_bps = ((ask - bid) / ((ask + bid) / 2)) * 10000
        if spread_bps > self.max_spread_bps:
            return RiskDecision(False, "Spread exceeds configured limit")
        if data_age_seconds is None or data_age_seconds > self.max_data_age_seconds:
            return RiskDecision(False, "Market data missing or stale")
        if self.realized_pnl_today <= -self.max_daily_loss_usdt:
            self.activate_kill_switch("Daily simulated loss limit reached")
            return RiskDecision(False, self.kill_switch_reason)
        return RiskDecision(True, "Approved for paper execution")

    def record_closed_trade(self, pnl_usdt: float) -> None:
        self.realized_pnl_today += pnl_usdt
        self.consecutive_losses = self.consecutive_losses + 1 if pnl_usdt < 0 else 0
        if self.realized_pnl_today <= -self.max_daily_loss_usdt:
            self.activate_kill_switch("Daily simulated loss limit reached")
        elif self.consecutive_losses >= self.max_consecutive_losses:
            self.activate_kill_switch("Consecutive-loss limit reached")

    def activate_kill_switch(self, reason: str) -> None:
        self.kill_switch = True
        self.kill_switch_reason = reason
