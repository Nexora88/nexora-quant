"""Cluster / correlation risk: one wallet risk budget, BTC throttle for alts."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OpenRiskSlot:
    symbol: str
    notional_usdt: float
    stop_loss_pct: float

    @property
    def risk_usdt(self) -> float:
        return max(0.0, self.notional_usdt) * max(0.0, self.stop_loss_pct) / 100.0


@dataclass
class PortfolioRiskGate:
    max_total_risk_pct: float = 0.35
    max_concurrent: int = 1
    _slots: dict[str, OpenRiskSlot] = field(default_factory=dict)

    def clear(self) -> None:
        self._slots.clear()

    def register(self, symbol: str, notional_usdt: float, stop_loss_pct: float) -> None:
        self._slots[symbol.lower()] = OpenRiskSlot(symbol.lower(), notional_usdt, stop_loss_pct)

    def unregister(self, symbol: str) -> None:
        self._slots.pop(symbol.lower(), None)

    def total_risk_usdt(self) -> float:
        return sum(s.risk_usdt for s in self._slots.values())

    def open_count(self) -> int:
        return len(self._slots)

    def can_open(
        self,
        *,
        symbol: str,
        notional_usdt: float,
        stop_loss_pct: float,
        equity_usdt: float,
        btc_blocks_alts: bool = False,
    ) -> tuple[bool, str]:
        sym = symbol.lower()
        if btc_blocks_alts and sym not in ("btcusdt", "btc"):
            return False, "btc_correlation_lock"
        if sym not in self._slots and self.open_count() >= self.max_concurrent:
            return False, f"max_concurrent={self.max_concurrent}"
        equity = max(1.0, float(equity_usdt))
        budget = equity * (self.max_total_risk_pct / 100.0)
        existing = sum(s.risk_usdt for k, s in self._slots.items() if k != sym)
        new_risk = max(0.0, notional_usdt) * max(0.0, stop_loss_pct) / 100.0
        if existing + new_risk > budget + 1e-9:
            return False, f"wallet_risk_{existing+new_risk:.3f}>budget_{budget:.3f}"
        return True, "ok"

    def size_for_budget(
        self,
        *,
        equity_usdt: float,
        stop_loss_pct: float,
        desired_usdt: float,
        symbol: str,
    ) -> float:
        if desired_usdt <= 0 or stop_loss_pct <= 0:
            return 0.0
        equity = max(1.0, float(equity_usdt))
        budget = equity * (self.max_total_risk_pct / 100.0)
        existing = sum(s.risk_usdt for k, s in self._slots.items() if k != symbol.lower())
        remaining = max(0.0, budget - existing)
        max_notional = remaining / (stop_loss_pct / 100.0)
        return max(0.0, min(desired_usdt, max_notional))
