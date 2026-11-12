"""Composite edge quality score — a cost gate, not a price prediction.

The alpha estimate is a research heuristic (regime/ATR-aware when caller
supplies it). Costs are round-trip basis points. Soft paper ceilings must be
opt-in so live never inherits a frozen-desk hack.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.decision import FeatureVote


@dataclass(slots=True)
class EdgeReport:
    quality: float
    agreement: float
    cost_bps: float
    net_edge_bps: float
    tradeable: bool
    notes: list[str]


def estimate_alpha_bps(
    *,
    take_profit_pct: float,
    atr_pct: float = 0.0,
    regime: str = "unknown",
    base_alpha_bps: float = 15.0,
) -> float:
    """Gross-move budget from TP target, ATR, and regime — not a forecast."""
    tp = max(0.0, float(take_profit_pct))
    atr = max(0.0, float(atr_pct))
    from_tp = tp * 100.0 * 0.85
    from_atr = atr * 10_000.0 * 0.35
    reg = (regime or "unknown").lower()
    regime_mul = 1.0
    if "trend" in reg or "break" in reg:
        regime_mul = 1.12
    elif "mean" in reg or "range" in reg or "chop" in reg:
        regime_mul = 0.90
    raw = max(float(base_alpha_bps) * 0.5, from_tp, from_atr)
    return max(8.0, min(80.0, raw * regime_mul))


def score_edge(
    *,
    votes: Sequence[FeatureVote],
    spread_bps: float,
    impact_bps: float = 0.0,
    fee_bps: float = 0.0,
    latency_bps: float = 0.0,
    expected_alpha_bps: float = 15.0,
    min_quality: float = 0.45,
    min_net_edge_bps: float = 2.0,
    paper_soft_gates: bool = False,
) -> EdgeReport:
    """Estimate net edge after costs; all costs are round-trip bps."""
    numeric = (
        spread_bps,
        impact_bps,
        fee_bps,
        latency_bps,
        expected_alpha_bps,
        min_quality,
        min_net_edge_bps,
    )
    if any(not isinstance(v, (int, float)) for v in numeric):
        raise ValueError("edge inputs must be numeric")
    if not 0 <= min_quality <= 1:
        raise ValueError("min_quality must be in [0, 1]")

    notes: list[str] = []
    if (
        spread_bps < 0
        or impact_bps < 0
        or fee_bps < 0
        or latency_bps < 0
        or expected_alpha_bps < 0
    ):
        notes.append("clamped_negative_cost_inputs")
    spread_bps = max(0.0, float(spread_bps))
    impact_bps = max(0.0, float(impact_bps))
    fee_bps = max(0.0, float(fee_bps))
    latency_bps = max(0.0, float(latency_bps))
    expected_alpha_bps = max(0.0, float(expected_alpha_bps))
    min_quality = float(min_quality)
    min_net_edge_bps = float(min_net_edge_bps)

    if not paper_soft_gates:
        import os

        mode = os.getenv("TRADING_MODE", "paper").strip().lower()
        env_soft = os.getenv("PAPER_SOFT_GATES", "true").strip().lower()
        if mode == "paper" and env_soft in {"1", "true", "yes", "on", ""}:
            paper_soft_gates = True
    if paper_soft_gates:
        min_quality = min(min_quality, 0.24)
        min_net_edge_bps = min(min_net_edge_bps, 0.35)
        notes.append("paper_soft_gates")

    total_cost = spread_bps + impact_bps + fee_bps + latency_bps
    if not votes:
        return EdgeReport(0.0, 0.0, total_cost, -total_cost, False, notes + ["no_votes"])

    long_w = sum(v.weight for v in votes if v.direction == "long")
    short_w = sum(v.weight for v in votes if v.direction == "short")
    total = long_w + short_w + sum(v.weight for v in votes if v.direction == "flat")
    majority = max(long_w, short_w)
    agreement = majority / total if total > 0 else 0.0
    gross = agreement * expected_alpha_bps
    net = gross - total_cost
    quality = max(0.0, min(1.0, agreement * (1.0 - min(0.7, total_cost / 30.0))))
    tradeable = quality >= min_quality and net >= min_net_edge_bps
    if not tradeable:
        if quality < min_quality:
            notes.append(f"quality_low={quality:.2f}")
        if net < min_net_edge_bps:
            notes.append(f"net_edge_bps={net:.2f}<{min_net_edge_bps:.2f}")
    else:
        notes.append(
            f"edge_ok q={quality:.2f} gross={gross:.2f} cost={total_cost:.2f} net={net:.2f}bps"
        )
    return EdgeReport(quality, agreement, total_cost, net, tradeable, notes)


def score_edge_for_desk(
    *,
    votes: Sequence[FeatureVote],
    spread_bps: float,
    impact_bps: float = 0.0,
    fee_bps: float = 0.0,
    latency_bps: float = 0.0,
    take_profit_pct: float = 0.55,
    atr_pct: float = 0.0,
    regime: str = "unknown",
    mode: str = "paper",
    entry_min_score: float = 0.20,
    paper_soft_gates: bool | None = None,
) -> EdgeReport:
    """Wire alpha + soft gates for the trading desk (paper vs live)."""
    alpha = estimate_alpha_bps(
        take_profit_pct=take_profit_pct,
        atr_pct=atr_pct,
        regime=regime,
    )
    soft = bool(paper_soft_gates) if paper_soft_gates is not None else (mode == "paper")
    if mode == "paper":
        return score_edge(
            votes=votes,
            spread_bps=spread_bps,
            impact_bps=impact_bps,
            fee_bps=fee_bps,
            latency_bps=latency_bps,
            expected_alpha_bps=alpha,
            min_quality=max(0.18, float(entry_min_score)),
            min_net_edge_bps=0.25 if soft else 1.0,
            paper_soft_gates=soft,
        )
    return score_edge(
        votes=votes,
        spread_bps=spread_bps,
        impact_bps=impact_bps,
        fee_bps=fee_bps,
        latency_bps=latency_bps,
        expected_alpha_bps=alpha,
        paper_soft_gates=False,
    )
