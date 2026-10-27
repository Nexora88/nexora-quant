"""Dynamic ATR / spread-scaled stop and take-profit (no fixed .env percentages)."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(slots=True)
class DynamicTargets:
    stop_loss_pct: float
    take_profit_pct: float
    trailing_stop_pct: float
    atr_pct: float
    note: str


class AtrTracker:
    def __init__(self, *, period: int = 28) -> None:
        self.period = max(5, int(period))
        self._mids: deque[float] = deque(maxlen=self.period + 2)
        self._trs: deque[float] = deque(maxlen=self.period)

    def update(self, mid: float) -> float:
        if mid <= 0:
            return 0.0
        if self._mids:
            prev = self._mids[-1]
            if prev > 0:
                self._trs.append(abs(mid - prev) / prev)
        self._mids.append(mid)
        if not self._trs:
            return 0.0
        return sum(self._trs) / len(self._trs)

    @property
    def atr_pct(self) -> float:
        if not self._trs:
            return 0.0
        return sum(self._trs) / len(self._trs)


def compute_dynamic_targets(
    *,
    atr_pct: float,
    spread_bps: float = 0.0,
    regime: str = "unknown",
    k_stop: float = 1.8,
    k_tp: float = 3.2,
    floor_sl: float = 0.20,
    ceiling_sl: float = 0.55,
    floor_tp: float = 0.45,
    ceiling_tp: float = 3.0,
    base_trail: float = 0.25,
) -> DynamicTargets:
    atr = max(0.0, float(atr_pct))
    spread_pct = max(0.0, float(spread_bps) / 100.0)
    raw_sl = k_stop * atr * 100.0
    raw_tp = k_tp * atr * 100.0
    raw_sl = max(raw_sl, spread_pct * 2.0)
    reg = (regime or "").lower()
    if reg in ("trend", "trending", "impulse"):
        raw_tp *= 1.35
        raw_sl *= 1.10
    elif reg in ("choppy", "range", "mean_revert", "mean-reversion"):
        raw_tp *= 0.75
        raw_sl *= 0.90
    elif reg in ("stressed", "crisis", "high_vol"):
        raw_sl *= 1.25
        raw_tp *= 0.85
    sl = max(floor_sl, min(ceiling_sl, raw_sl if raw_sl > 0 else floor_sl))
    tp = max(floor_tp, min(ceiling_tp, raw_tp if raw_tp > 0 else floor_tp))
    if tp < sl * 1.4:
        tp = min(ceiling_tp, sl * 1.4)
    trail = max(0.12, min(sl * 0.85, base_trail + atr * 50.0))
    note = f"atr={atr*100:.3f}% sl={sl:.2f}% tp={tp:.2f}% reg={reg or 'na'}"
    return DynamicTargets(sl, tp, trail, atr, note)
