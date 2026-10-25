"""Multi-factor research signals: order-book imbalance, micro-momentum, target-price bias.

These are heuristics for experimentation, not predictions or guaranteed edge.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime

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
    """Snapshot of book + short-horizon price structure for the dashboard."""

    mid: float
    spread_bps: float
    imbalance: float
    momentum_bps: float
    trend: str  # up | down | flat
    distance_to_target_pct: float | None
    target_bias: str  # approach_buy | approach_sell | none
    score: float  # composite -1..+1 (positive favors long)
    reasons: list[str]
    created_at: datetime


class PriceWindow:
    """Rolling mid-price samples for micro-momentum."""

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
) -> MarketAnalysis:
    mid = (bid + ask) / 2 if bid > 0 and ask >= bid else 0.0
    spread_bps = ((ask - bid) / mid * 10_000) if mid > 0 else 0.0
    imb = imbalance_strength(bid_qty, ask_qty)
    price_window.push(mid)
    mom = price_window.momentum_bps(20)
    if mom > 3:
        trend = "up"
    elif mom < -3:
        trend = "down"
    else:
        trend = "flat"

    dist: float | None = None
    target_bias = "none"
    if target_price and target_price > 0 and mid > 0:
        dist = ((target_price / mid) - 1.0) * 100
        if dist > 0.15:
            target_bias = "approach_buy"
        elif dist < -0.15:
            target_bias = "approach_sell"

    reasons: list[str] = []
    score = 0.0
    if imb >= imbalance_threshold:
        score += 0.45
        reasons.append(f"bid_imbalance={imb:.2f}")
    elif imb <= 1 - imbalance_threshold:
        score -= 0.35
        reasons.append(f"ask_imbalance={imb:.2f}")
    if mom > 5:
        score += 0.25
        reasons.append(f"momentum_up={mom:.1f}bps")
    elif mom < -5:
        score -= 0.25
        reasons.append(f"momentum_down={mom:.1f}bps")
    if target_bias == "approach_buy":
        score += 0.30
        reasons.append(f"below_target={dist:.2f}%")
    elif target_bias == "approach_sell":
        score -= 0.20
        reasons.append(f"above_target={dist:.2f}%")
    if spread_bps > 15:
        score *= 0.5
        reasons.append(f"wide_spread={spread_bps:.1f}bps")

    score = max(-1.0, min(1.0, score))
    return MarketAnalysis(
        mid=mid,
        spread_bps=spread_bps,
        imbalance=imb,
        momentum_bps=mom,
        trend=trend,
        distance_to_target_pct=dist,
        target_bias=target_bias,
        score=score,
        reasons=reasons or ["neutral"],
        created_at=utc_now(),
    )


def entry_signal_from_analysis(
    analysis: MarketAnalysis, *, min_score: float = 0.55
) -> Signal | None:
    if analysis.score >= min_score:
        return Signal(
            "buy",
            "composite:" + ",".join(analysis.reasons[:3]),
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
    """Priority: hard stop -> trailing stop -> take profit -> absolute target."""
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
