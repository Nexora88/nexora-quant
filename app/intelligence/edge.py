"""Composite edge quality score — a cost gate, not a price prediction.

The alpha estimate is an explicit research heuristic. Costs are expressed in
basis points and must include the complete entry/exit round trip. The gate
refuses setups whose estimated gross edge does not cover costs.
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
) -> EdgeReport:
    """Estimate net edge after costs; all costs are round-trip bps.

    expected_alpha_bps is a heuristic gross-move budget, not a calibrated
    forecast. fee_bps should include both entry and exit fees. Spread, impact,
    and latency/adverse-selection allowances should cover the round trip too.
    """
    numeric = (spread_bps, impact_bps, fee_bps, latency_bps, expected_alpha_bps,
               min_quality, min_net_edge_bps)
    if any(not isinstance(v, (int, float)) for v in numeric):
        raise ValueError("edge inputs must be numeric")
    if any(v < 0 for v in (spread_bps, impact_bps, fee_bps, latency_bps,
                           expected_alpha_bps, min_net_edge_bps)):
        raise ValueError("costs, expected alpha, and minimum edge cannot be negative")
    if not 0 <= min_quality <= 1:
        raise ValueError("min_quality must be in [0, 1]")

    notes: list[str] = []
    total_cost = spread_bps + impact_bps + fee_bps + latency_bps
    if not votes:
        return EdgeReport(0.0, 0.0, total_cost, -total_cost, False, ["no_votes"])

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
        notes.append(f"edge_ok q={quality:.2f} gross={gross:.2f} cost={total_cost:.2f} net={net:.2f}bps")
    return EdgeReport(quality, agreement, total_cost, net, tradeable, notes)
