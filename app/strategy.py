"""Multi-factor research signals with microstructure math and regime awareness.

Uses weighted multi-level OBI, micro-price premium, OU z-score mean-reversion,
momentum, and optional target bias. Heuristics for research — not guaranteed edge.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from app.analytics.microstructure import (
    OrnsteinUhlenbeckTracker,
    build_snapshot,
)
from app.analytics.regime import MarketRegime, RegimeClassifier, RegimeSnapshot
from app.events import Signal, utc_now


def imbalance_strength(bid_qty: float, ask_qty: float) -> float:
    if bid_qty < 0 or ask_qty < 0:
        raise ValueError("Quote quantities cannot be negative")
    total = bid_qty + ask_qty
    return 0.5 if total == 0 else bid_qty / total


def evaluate_imbalance(
    bid_qty: float, ask_qty: float, threshold: float = 0.70
) -> Signal | None:
    if not 0.5 < threshold <= 1:
        raise ValueError("threshold must be in (0.5, 1]")
    strength = imbalance_strength(bid_qty, ask_qty)
    if strength >= threshold:
        return Signal("buy", "top_of_book_bid_imbalance", strength, utc_now())
    return None


@dataclass(slots=True)
class MarketAnalysis:
    mid: float
    spread_bps: float
    imbalance: float
    momentum_bps: float
    trend: str
    distance_to_target_pct: float | None
    target_bias: str
    score: float
    reasons: list[str]
    created_at: datetime
    weighted_obi: float | None = None
    micro_price: float | None = None
    micro_premium_bps: float = 0.0
    ou_zscore: float | None = None
    mean_reversion_signal: str = "none"
    regime: str = "unknown"


class PriceWindow:
    def __init__(self, maxlen: int = 120) -> None:
        self._mids: deque[float] = deque(maxlen=maxlen)

    def push(self, mid: float) -> None:
        if mid > 0:
            self._mids.append(mid)

    def momentum_bps(self, lookback: int = 20) -> float:
        if len(self._mids) < max(2, lookback // 2):
            return 0.0
        n = min(lookback, len(self._mids))
        oldest = self._mids[-n]
        newest = self._mids[-1]
        if oldest <= 0:
            return 0.0
        return ((newest / oldest) - 1.0) * 10_000

    def last(self) -> float | None:
        return self._mids[-1] if self._mids else None


def analyze_market(
    *,
    bid: float,
    ask: float,
    bid_qty: float,
    ask_qty: float,
    price_window: PriceWindow,
    imbalance_threshold: float,
    target_price: float | None = None,
    bids: Sequence[tuple[float, float]] | None = None,
    asks: Sequence[tuple[float, float]] | None = None,
    ou: OrnsteinUhlenbeckTracker | None = None,
    regime_classifier: RegimeClassifier | None = None,
    wall_bias: float = 0.0,
) -> MarketAnalysis:
    mid = (bid + ask) / 2 if bid > 0 and ask >= bid else 0.0
    spread_bps = ((ask - bid) / mid * 10_000) if mid > 0 else 0.0
    if mid > 0:
        price_window.push(mid)
    mom = price_window.momentum_bps()
    trend = "up" if mom > 3 else "down" if mom < -3 else "flat"

    snap = build_snapshot(
        bid=bid, ask=ask, bid_qty=bid_qty, ask_qty=ask_qty,
        bids=bids, asks=asks, ou=ou, levels=10,
    )
    imb = snap.weighted_obi if snap.weighted_obi is not None else imbalance_strength(bid_qty, ask_qty)
    imb_01 = (imb + 1.0) / 2.0 if snap.weighted_obi is not None else imb

    dist = None
    target_bias = "none"
    if target_price and target_price > 0 and mid > 0:
        dist = (target_price / mid - 1.0) * 100
        if dist > 0.15:
            target_bias = "approach_buy"
        elif dist < -0.15:
            target_bias = "approach_sell"

    regime_snap: RegimeSnapshot | None = None
    if regime_classifier is not None:
        regime_snap = regime_classifier.update(
            mid=mid, spread_bps=spread_bps, volume_proxy=bid_qty + ask_qty
        )

    reasons: list[str] = []
    score = 0.0
    regime = regime_snap.regime if regime_snap else MarketRegime.UNKNOWN

    hard_block = False
    if regime == MarketRegime.STRESSED:
        reasons.append("regime_stressed")
        hard_block = True
    elif regime_snap is not None and regime_snap.pause_entries:
        reasons.append(f"regime_pause:{regime_snap.detail}")
        hard_block = True

    if hard_block:
        score = 0.0
    elif regime == MarketRegime.RANGE:
        if snap.mean_reversion_signal == "fade_ask":
            score += 0.50
            reasons.append(f"ou_fade_ask z={snap.ou_zscore:.2f}" if snap.ou_zscore is not None else "ou_fade_ask")
        elif snap.mean_reversion_signal == "fade_bid":
            score -= 0.45
            reasons.append(f"ou_fade_bid z={snap.ou_zscore:.2f}" if snap.ou_zscore is not None else "ou_fade_bid")
        if snap.micro_premium_bps < -1.5:
            score += 0.20
            reasons.append(f"micro_cheap={snap.micro_premium_bps:.1f}bps")
        elif snap.micro_premium_bps > 1.5:
            score -= 0.15
            reasons.append(f"micro_rich={snap.micro_premium_bps:.1f}bps")
    else:
        if snap.weighted_obi is not None:
            if snap.weighted_obi >= (2 * imbalance_threshold - 1):
                score += 0.40
                reasons.append(f"w_obi={snap.weighted_obi:.2f}")
            elif snap.weighted_obi <= -(2 * imbalance_threshold - 1):
                score -= 0.35
                reasons.append(f"w_obi={snap.weighted_obi:.2f}")
        else:
            if imb_01 >= imbalance_threshold:
                score += 0.35
                reasons.append(f"tob_imb={imb_01:.2f}")
            elif imb_01 <= 1 - imbalance_threshold:
                score -= 0.30
                reasons.append(f"tob_imb={imb_01:.2f}")
        if snap.micro_premium_bps > 1.0:
            score += 0.20
            reasons.append(f"micro_up={snap.micro_premium_bps:.1f}bps")
        elif snap.micro_premium_bps < -1.0:
            score -= 0.15
            reasons.append(f"micro_dn={snap.micro_premium_bps:.1f}bps")
        if mom > 5:
            score += 0.25
            reasons.append(f"mom_up={mom:.1f}bps")
        elif mom < -5:
            score -= 0.25
            reasons.append(f"mom_dn={mom:.1f}bps")

    if wall_bias >= 0.25:
        score += 0.18
        reasons.append(f"bid_walls={wall_bias:.2f}")
    elif wall_bias <= -0.25:
        score -= 0.15
        reasons.append(f"ask_walls={wall_bias:.2f}")
    if target_bias == "approach_buy":
        score += 0.20
        reasons.append(f"below_target={dist:.2f}%")
    elif target_bias == "approach_sell":
        score -= 0.15
        reasons.append(f"above_target={dist:.2f}%")

    if spread_bps > 15:
        score *= 0.5
        reasons.append(f"wide_spread={spread_bps:.1f}bps")

    if regime == MarketRegime.CHOPPY:
        if "regime_choppy" not in reasons:
            reasons.append("regime_choppy")
        score *= 0.55
    score = max(-1.0, min(1.0, score))
    return MarketAnalysis(
        mid=mid,
        spread_bps=spread_bps,
        imbalance=imb_01 if snap.weighted_obi is None else (snap.weighted_obi + 1) / 2,
        momentum_bps=mom,
        trend=trend,
        distance_to_target_pct=dist,
        target_bias=target_bias,
        score=score,
        reasons=reasons or ["neutral"],
        created_at=utc_now(),
        weighted_obi=snap.weighted_obi,
        micro_price=snap.micro_price,
        micro_premium_bps=snap.micro_premium_bps,
        ou_zscore=snap.ou_zscore,
        mean_reversion_signal=snap.mean_reversion_signal,
        regime=regime.value if isinstance(regime, MarketRegime) else str(regime),
    )


def entry_signal_from_analysis(
    analysis: MarketAnalysis, *, min_score: float = 0.55
) -> Signal | None:
    if analysis.regime == MarketRegime.STRESSED.value:
        return None
    if any(r.startswith("regime_pause") for r in analysis.reasons):
        return None
    need = float(min_score)
    if analysis.regime == MarketRegime.CHOPPY.value:
        need = min(0.95, need + 0.08)
    if analysis.score >= need:
        return Signal(
            "buy",
            "composite:" + ",".join(analysis.reasons[:4]),
            analysis.score,
            analysis.created_at,
        )
    return None


def exit_reason(
    *,
    bid: float,
    average_entry: float,
    take_profit_pct: float,
    stop_loss_pct: float,
    trailing_stop_pct: float,
    peak_price: float,
    target_price: float | None,
) -> str | None:
    if average_entry <= 0 or bid <= 0:
        return None
    move = (bid / average_entry - 1.0) * 100
    if move <= -stop_loss_pct:
        return "stop_loss"
    if trailing_stop_pct > 0 and peak_price > average_entry:
        trail_floor = peak_price * (1.0 - trailing_stop_pct / 100.0)
        if bid <= trail_floor:
            return "trailing_stop"
    if move >= take_profit_pct:
        return "take_profit"
    if target_price and target_price > 0 and bid >= target_price:
        return "target_price"
    return None
