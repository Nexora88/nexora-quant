"""Dynamic ATR / spread-scaled stop and take-profit (scalp-friendly floors).

Default band targets ~0.15–0.30% SL and ~0.40–0.90% TP so round-trip fees
can still be beaten on Spot while order-flow (1–3s) remains meaningful.
"""
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
    k_stop: float = 1.5,
    k_tp: float = 2.8,
    floor_sl: float = 0.15,
    ceiling_sl: float = 0.32,
    floor_tp: float = 0.40,
    ceiling_tp: float = 0.90,
    base_trail: float = 0.12,
    fee_round_trip_pct: float = 0.20,
) -> DynamicTargets:
    """Scalp band: TP must clear fee_round_trip with margin; SL stays tight."""
    atr = max(0.0, float(atr_pct))
    spread_pct = max(0.0, float(spread_bps) / 100.0)
    raw_sl = k_stop * atr * 100.0
    raw_tp = k_tp * atr * 100.0
    raw_sl = max(raw_sl, spread_pct * 2.0)
    reg = (regime or "").lower()
    if reg in ("trend", "trending", "impulse"):
        raw_tp *= 1.25
        raw_sl *= 1.05
    elif reg in ("choppy", "range", "mean_revert", "mean-reversion"):
        raw_tp *= 0.85
        raw_sl *= 0.92
    elif reg in ("stressed", "crisis", "high_vol"):
        raw_sl *= 1.20
        raw_tp *= 0.90
    sl = max(floor_sl, min(ceiling_sl, raw_sl if raw_sl > 0 else floor_sl))
    tp = max(floor_tp, min(ceiling_tp, raw_tp if raw_tp > 0 else floor_tp))
    fee_floor = max(0.0, float(fee_round_trip_pct)) * 1.6
    if tp < fee_floor:
        tp = min(ceiling_tp, max(tp, fee_floor, floor_tp))
    if tp < sl * 1.8:
        tp = min(ceiling_tp, max(tp, sl * 1.8))
    trail = max(0.08, min(sl * 0.80, base_trail + atr * 40.0))
    note = (
        f"scalp atr={atr*100:.3f}% sl={sl:.2f}% tp={tp:.2f}% "
        f"fee_rt={fee_round_trip_pct:.2f}% reg={reg or 'na'}"
    )
    return DynamicTargets(sl, tp, trail, atr, note)


@dataclass(slots=True)
class WickStopState:
    """Require N consecutive ticks below stop before hard stop (wick filter)."""
    below_count: int = 0


def wick_aware_stop(
    *,
    move_pct: float,
    stop_loss_pct: float,
    state: WickStopState,
    confirmations: int = 2,
) -> bool:
    """True only if price stayed below -SL for `confirmations` consecutive checks."""
    if move_pct <= -stop_loss_pct:
        state.below_count += 1
    else:
        state.below_count = 0
    return state.below_count >= max(1, int(confirmations))
