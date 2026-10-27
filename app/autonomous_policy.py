"""Fully autonomous trade policy: liquidity gate, vol sizing, regime TP/SL.

Designed to reduce commission bleed from tight fixed stops in the wrong regime
and to refuse shallow books that stop-hunt retail size.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


_MIN_DEPTH_USDT: dict[str, float] = {
    "btcusdt": 40_000.0,
    "ethusdt": 20_000.0,
    "solusdt": 8_000.0,
    "bnbusdt": 8_000.0,
}
_DEFAULT_MIN_DEPTH = 6_000.0
_MAX_SPREAD_BPS_LIQUID = 12.0


@dataclass(slots=True)
class LiquidityVerdict:
    ok: bool
    depth_usdt: float
    spread_bps: float
    min_required: float
    note: str


def visible_depth_usdt(levels: Sequence[tuple[float, float]], *, top: int = 15) -> float:
    total = 0.0
    for i, row in enumerate(levels):
        if i >= top:
            break
        if len(row) < 2:
            continue
        px, qty = float(row[0]), float(row[1])
        if px > 0 and qty > 0:
            total += px * qty
    return total


def assess_liquidity(
    *,
    symbol: str,
    bids: Sequence[tuple[float, float]],
    asks: Sequence[tuple[float, float]],
    spread_bps: float,
    min_depth_override: float | None = None,
) -> LiquidityVerdict:
    """Reject shallow books and wide spreads (stop-hunt / illiquid alts)."""
    sym = (symbol or "").lower()
    min_req = min_depth_override if min_depth_override is not None else _MIN_DEPTH_USDT.get(
        sym, _DEFAULT_MIN_DEPTH
    )
    depth = visible_depth_usdt(bids) + visible_depth_usdt(asks)
    if spread_bps > _MAX_SPREAD_BPS_LIQUID:
        return LiquidityVerdict(
            False, depth, spread_bps, min_req, f"spread_{spread_bps:.1f}bps>max"
        )
    if depth < min_req:
        return LiquidityVerdict(
            False, depth, spread_bps, min_req, f"depth_{depth:.0f}<min_{min_req:.0f}"
        )
    return LiquidityVerdict(True, depth, spread_bps, min_req, "liquid_ok")


@dataclass(slots=True)
class RegimeTargets:
    take_profit_pct: float
    stop_loss_pct: float
    trailing_stop_pct: float
    size_scale: float
    note: str


def regime_targets(
    *,
    regime: str,
    base_tp: float = 1.20,
    base_sl: float = 0.35,
    base_trail: float = 0.25,
    vol_bps: float = 0.0,
) -> RegimeTargets:
    """Widen targets in trends; tighten in chop; shrink size when vol spikes."""
    reg = (regime or "unknown").lower()
    vol = max(0.0, float(vol_bps))

    if reg in ("trend", "trending", "impulse"):
        tp = max(base_tp, 2.0)
        if vol > 25:
            tp = max(tp, 2.5)
        if vol > 40:
            tp = max(tp, 3.0)
        sl = max(base_sl, 0.45)
        trail = max(base_trail, 0.35)
        scale = 1.0
        note = f"trend_tp={tp:.2f}_sl={sl:.2f}"
    elif reg in ("choppy", "range", "mean_revert", "mean-reversion"):
        tp = min(base_tp, 0.70)
        sl = min(base_sl, 0.30)
        trail = min(base_trail, 0.20)
        scale = 0.55
        note = f"chop_tp={tp:.2f}_sl={sl:.2f}_scale={scale:.2f}"
    elif reg in ("stressed", "crisis", "high_vol"):
        tp = min(base_tp, 0.80)
        sl = max(base_sl, 0.55)
        trail = 0.40
        scale = 0.25
        note = f"stress_scale={scale:.2f}"
    else:
        tp, sl, trail, scale = base_tp, base_sl, base_trail, 0.85
        note = "neutral_baseline"

    if vol <= 12:
        scale *= 1.25
    elif vol <= 25:
        scale *= 1.0
    elif vol <= 40:
        scale *= 0.65
    else:
        scale *= 0.35

    scale = max(0.15, min(1.35, scale))
    if tp < sl * 1.5:
        tp = sl * 1.5
    return RegimeTargets(tp, sl, trail, scale, note)


def vol_adjusted_notional(
    *,
    base_notional: float,
    size_scale: float,
    min_order_usdt: float,
    max_order_usdt: float,
) -> float:
    if base_notional <= 0:
        return 0.0
    n = base_notional * max(0.0, size_scale)
    n = min(max_order_usdt, n)
    if n < min_order_usdt:
        return 0.0
    return round(n, 8)
