"""Central pre-trade risk gate for simulated orders."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Durable kill-switch file so Restart=always cannot clear same-day brakes.
_KILL_FILE = Path("data/risk_kill_switch.json")


@dataclass(frozen=True, slots=True)
class RiskDecision:
    allowed: bool
    reason: str


class RiskManager:
    def __init__(self, *, max_order_size_usdt: float, max_daily_loss_usdt: float,
                 max_consecutive_losses: int, max_spread_bps: float,
                 max_data_age_seconds: float, max_daily_fee_usdt: float = float("inf")) -> None:
        self.max_order_size_usdt = max_order_size_usdt
        self.max_daily_loss_usdt = max_daily_loss_usdt
        self.max_consecutive_losses = max_consecutive_losses
        self.max_spread_bps = max_spread_bps
        self.max_data_age_seconds = max_data_age_seconds
        self.max_daily_fee_usdt = float(max_daily_fee_usdt)
        if self.max_daily_fee_usdt <= 0:
            raise ValueError("max_daily_fee_usdt must be positive")
        self.fees_paid_today = 0.0
        self.realized_pnl_today = 0.0
        self.consecutive_losses = 0
        self.kill_switch = False
        self.kill_switch_reason = None
        self.day_utc: str | None = None
        # Only live mode uses durable kill file (survives systemd Restart=always).
        if self._durable_enabled():
            self._load_durable_kill()

    @staticmethod
    def _durable_enabled() -> bool:
        import os

        mode = (os.getenv("TRADING_MODE") or "paper").strip().lower()
        force = (os.getenv("NEXORA_DURABLE_KILL") or "").strip().lower() in {
            "1", "true", "yes", "on",
        }
        return force or mode == "live"

    def snapshot(self) -> dict[str, Any]:
        return {
            "realized_pnl_today": float(self.realized_pnl_today),
            "fees_paid_today": float(self.fees_paid_today),
            "consecutive_losses": int(self.consecutive_losses),
            "kill_switch": bool(self.kill_switch),
            "kill_switch_reason": self.kill_switch_reason,
            "day_utc": self.day_utc,
        }

    def restore(self, data: dict[str, Any] | None) -> None:
        if not data:
            if self._durable_enabled():
                self._load_durable_kill()
            return
        self.realized_pnl_today = float(data.get("realized_pnl_today", 0) or 0)
        self.fees_paid_today = max(0.0, float(data.get("fees_paid_today", 0) or 0))
        self.consecutive_losses = int(data.get("consecutive_losses", 0) or 0)
        self.kill_switch = bool(data.get("kill_switch", False))
        self.kill_switch_reason = data.get("kill_switch_reason")
        self.day_utc = data.get("day_utc")
        # Durable kill file wins if still active (live only).
        if self._durable_enabled():
            self._load_durable_kill(merge=True)

    def _load_durable_kill(self, *, merge: bool = False) -> None:
        try:
            if not _KILL_FILE.is_file():
                return
            payload = json.loads(_KILL_FILE.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not payload.get("kill_switch"):
                return
            if merge and self.kill_switch:
                return
            self.kill_switch = True
            self.kill_switch_reason = payload.get("kill_switch_reason") or self.kill_switch_reason
            if payload.get("day_utc"):
                self.day_utc = payload.get("day_utc")
            if "realized_pnl_today" in payload:
                self.realized_pnl_today = float(payload.get("realized_pnl_today") or 0)
            if "consecutive_losses" in payload:
                self.consecutive_losses = int(payload.get("consecutive_losses") or 0)
            log.warning("Restored durable kill switch: %s", self.kill_switch_reason)
        except Exception:
            log.exception("Failed to load durable kill switch file")

    def _persist_durable_kill(self) -> None:
        if not self._durable_enabled():
            return
        try:
            _KILL_FILE.parent.mkdir(parents=True, exist_ok=True)
            if self.kill_switch:
                _KILL_FILE.write_text(
                    json.dumps(self.snapshot(), indent=2),
                    encoding="utf-8",
                )
            elif _KILL_FILE.is_file():
                _KILL_FILE.unlink(missing_ok=True)
        except Exception:
            log.exception("Failed to persist durable kill switch")

    def rollover_day(self, day_utc: str) -> bool:
        """Reset only the daily counter at UTC date change; preserve other risk brakes."""
        if self.day_utc == day_utc:
            return False
        self.day_utc = day_utc
        self.realized_pnl_today = 0.0
        self.fees_paid_today = 0.0
        if self.kill_switch_reason in {"Daily loss limit reached", "Daily fee budget reached"}:
            self.kill_switch = False
            self.kill_switch_reason = None
            self._persist_durable_kill()
        return True

    def evaluate_entry(self, *, notional_usdt: float, available_cash: float,
                       bid: float, ask: float, data_age_seconds: float | None) -> RiskDecision:
        if self.kill_switch:
            return RiskDecision(False, self.kill_switch_reason or "Kill switch active")
        if self.fees_paid_today >= self.max_daily_fee_usdt:
            return RiskDecision(False, "Daily fee budget reached")
        if notional_usdt <= 0:
            return RiskDecision(False, "Order notional must be positive")
        if notional_usdt > self.max_order_size_usdt:
            return RiskDecision(False, "Order exceeds configured maximum")
        if notional_usdt > available_cash:
            return RiskDecision(False, "Insufficient available cash")
        if bid <= 0 or ask <= 0 or ask < bid:
            return RiskDecision(False, "Invalid bid/ask market")
        spread_bps = ((ask - bid) / ((ask + bid) / 2)) * 10000
        if spread_bps > self.max_spread_bps:
            return RiskDecision(False, "Spread exceeds configured limit")
        if data_age_seconds is None or data_age_seconds > self.max_data_age_seconds:
            return RiskDecision(False, "Market data missing or stale")
        if self.realized_pnl_today <= -self.max_daily_loss_usdt:
            self.activate_kill_switch("Daily loss limit reached")
            return RiskDecision(False, self.kill_switch_reason)
        return RiskDecision(True, "Approved for execution")

    def record_fee(self, fee_usdt: float) -> None:
        """Count actual reported execution fees toward the UTC-day entry budget."""
        fee = float(fee_usdt)
        if fee < 0:
            raise ValueError("fee_usdt cannot be negative")
        self.fees_paid_today += fee

    def record_realized_pnl(self, pnl_usdt: float, *, position_closed: bool = True) -> None:
        """Count every realized fill toward daily loss, but only completed exits toward streaks."""
        self.realized_pnl_today += pnl_usdt
        if position_closed:
            self.consecutive_losses = self.consecutive_losses + 1 if pnl_usdt < 0 else 0
        if self.realized_pnl_today <= -self.max_daily_loss_usdt:
            self.activate_kill_switch("Daily loss limit reached")
        elif position_closed and self.consecutive_losses >= self.max_consecutive_losses:
            self.activate_kill_switch("Consecutive-loss limit reached")

    def record_closed_trade(self, pnl_usdt: float) -> None:
        """Backward-compatible alias for a fully closed simulated position."""
        self.record_realized_pnl(pnl_usdt, position_closed=True)

    def activate_kill_switch(self, reason: str) -> None:
        was = self.kill_switch
        self.kill_switch = True
        self.kill_switch_reason = reason
        self._persist_durable_kill()
        if not was:
            try:
                from app.alerts import alert_kill_switch

                alert_kill_switch(reason)
            except Exception:
                pass

    def clear_kill_switch(self) -> None:
        self.kill_switch = False
        self.kill_switch_reason = None
        self._persist_durable_kill()
