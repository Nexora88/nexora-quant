"""Composite edge quality score — not a price prediction.

Combines agreement across features, regime fit, and cost of spread/impact so the
bot can refuse low-quality setups instead of always trading a raw signal.
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
    min_quality: float = 0.45,
    min_net_edge_bps: float = 2.0,
) -> EdgeReport:
    notes: list[str] = []
    if not votes:
        return EdgeReport(0.0, 0.0, spread_bps + impact_bps, -spread_bps, False, ["no_votes"])

    long_w = sum(v.weight for v in votes if v.direction == "long")
    short_w = sum(v.weight for v in votes if v.direction == "short")
    total = long_w + short_w + sum(v.weight for v in votes if v.direction == "flat")
    majority = max(long_w, short_w)
    agreement = (majority / total) if total > 0 else 0.0
    cost = max(0.0, spread_bps) + max(0.0, impact_bps)
    raw = agreement * 15.0
    net = raw - cost
    quality = max(0.0, min(1.0, agreement * (1.0 - min(0.7, cost / 30.0))))
    tradeable = quality >= min_quality and net >= min_net_edge_bps
    if not tradeable:
        if quality < min_quality:
            notes.append(f"quality_low={quality:.2f}")
        if net < min_net_edge_bps:
            notes.append(f"net_edge_bps={net:.1f}<{min_net_edge_bps}")
    else:
        notes.append(f"edge_ok q={quality:.2f} net={net:.1f}bps")
    return EdgeReport(quality, agreement, cost, net, tradeable, notes)
