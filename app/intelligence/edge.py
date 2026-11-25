"""Composite edge score and hard transaction-cost multiple gate.

Expected alpha is a research heuristic, not a forecast. All costs are
round-trip basis points. The cost-multiple gate remains hard in paper and live.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
from typing import Literal, Sequence

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
    """Gross-move budget from TP, ATR and regime; deliberately not a forecast."""
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
    min_cost_multiple: float = 2.0,
    paper_soft_gates: bool = False,
    side: Literal["long", "short"] | None = None,
) -> EdgeReport:
    """Score alignment separately; require gross edge >= N times round-trip costs."""
    numeric = (
        spread_bps, impact_bps, fee_bps, latency_bps, expected_alpha_bps,
        min_quality, min_net_edge_bps, min_cost_multiple,
    )
    if any(not isinstance(v, (int, float)) or not math.isfinite(float(v)) for v in numeric):
        raise ValueError("edge inputs must be finite numbers")
    if not 0 <= min_quality <= 1:
        raise ValueError("min_quality must be in [0, 1]")
    if min_cost_multiple < 1.0:
        raise ValueError("min_cost_multiple must be >= 1")

    notes: list[str] = []
    if min(spread_bps, impact_bps, fee_bps, latency_bps, expected_alpha_bps) < 0:
        notes.append("clamped_negative_cost_inputs")
    spread_bps = max(0.0, float(spread_bps))
    impact_bps = max(0.0, float(impact_bps))
    fee_bps = max(0.0, float(fee_bps))
    latency_bps = max(0.0, float(latency_bps))
    expected_alpha_bps = max(0.0, float(expected_alpha_bps))
    min_quality = float(min_quality)
    min_net_edge_bps = float(min_net_edge_bps)
    min_cost_multiple = float(min_cost_multiple)

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
    aligned = long_w if side == "long" else short_w if side == "short" else max(long_w, short_w)
    agreement = aligned / total if total > 0 else 0.0
    gross = agreement * expected_alpha_bps
    net = gross - total_cost
    # Costs already affect both the net edge and the cost multiple. Penalizing
    # agreement again made the quality threshold unreachable at common fees.
    quality = max(0.0, min(1.0, agreement))
    multiple_ok = total_cost <= 0.0 or gross >= total_cost * min_cost_multiple
    tradeable = quality >= min_quality and net >= min_net_edge_bps and multiple_ok
    if not multiple_ok:
        notes.append(
            f"cost_multiple_low={gross / total_cost:.2f}<{min_cost_multiple:.2f}"
        )
    if not tradeable:
        if quality < min_quality:
            notes.append(f"quality_low={quality:.2f}")
        if net < min_net_edge_bps:
            notes.append(f"net_edge_bps={net:.2f}<{min_net_edge_bps:.2f}")
    else:
        notes.append(
            f"edge_ok q={quality:.2f} gross={gross:.2f} cost={total_cost:.2f} "
            f"net={net:.2f}bps multiple={gross / total_cost if total_cost else float('inf'):.2f}x"
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
    min_cost_multiple: float = 2.0,
    paper_soft_gates: bool | None = None,
) -> EdgeReport:
    """Wire alpha + mode gates; soft paper gates never relax the cost multiple."""
    alpha = estimate_alpha_bps(
        take_profit_pct=take_profit_pct,
        atr_pct=atr_pct,
        regime=regime,
    )
    if paper_soft_gates is None:
        env_soft = os.getenv("PAPER_SOFT_GATES", "false").strip().lower()
        soft = mode == "paper" and env_soft in {"1", "true", "yes", "on"}
    else:
        soft = bool(paper_soft_gates) and mode == "paper"
    if mode == "paper":
        return score_edge(
            votes=votes, spread_bps=spread_bps, impact_bps=impact_bps,
            fee_bps=fee_bps, latency_bps=latency_bps,
            expected_alpha_bps=alpha,
            min_quality=max(0.18, float(entry_min_score)),
            min_net_edge_bps=0.25 if soft else 1.0,
            min_cost_multiple=min_cost_multiple,
            paper_soft_gates=soft,
            side="long",
        )
    return score_edge(
        votes=votes, spread_bps=spread_bps, impact_bps=impact_bps,
        fee_bps=fee_bps, latency_bps=latency_bps,
        expected_alpha_bps=alpha,
        min_cost_multiple=min_cost_multiple,
        paper_soft_gates=False,
        side="long",
    )
