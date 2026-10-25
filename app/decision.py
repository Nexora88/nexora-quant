"""Decision layer: fuse microstructure, regime, walls, sustained gate into an audited choice.

Produces a structured DecisionRecord every tick for the dashboard and ledger —
not a black-box score, but an explainable vote of research features.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.analytics.regime import MarketRegime
from app.analytics.sustained import SustainedDecision
from app.strategy import MarketAnalysis


@dataclass(slots=True)
class FeatureVote:
    name: str
    direction: str
    weight: float
    value: float | None
    note: str


@dataclass(slots=True)
class DecisionRecord:
    action: str
    confidence: float
    regime: str
    score: float
    votes: list[FeatureVote] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    sustained: dict[str, Any] | None = None
    kelly_fraction: float | None = None
    suggested_notional_usdt: float | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _vote(name: str, direction: str, weight: float, value: float | None, note: str) -> FeatureVote:
    return FeatureVote(name=name, direction=direction, weight=weight, value=value, note=note)


def build_decision(
    *,
    analysis: MarketAnalysis,
    sustained: SustainedDecision | None = None,
    in_position: bool = False,
    kill_switch: bool = False,
    kill_reason: str | None = None,
    kelly_fraction: float | None = None,
    suggested_notional: float | None = None,
    entry_min_score: float = 0.55,
) -> DecisionRecord:
    votes: list[FeatureVote] = []
    blockers: list[str] = []
    rationale: list[str] = []

    if analysis.weighted_obi is not None:
        if analysis.weighted_obi > 0.25:
            votes.append(_vote("weighted_obi", "long", 0.35, analysis.weighted_obi, f"OBI={analysis.weighted_obi:.3f}"))
        elif analysis.weighted_obi < -0.25:
            votes.append(_vote("weighted_obi", "short", 0.35, analysis.weighted_obi, f"OBI={analysis.weighted_obi:.3f}"))
        else:
            votes.append(_vote("weighted_obi", "flat", 0.1, analysis.weighted_obi, "OBI neutral"))

    if analysis.micro_premium_bps != 0:
        if analysis.micro_premium_bps > 1.0:
            votes.append(_vote("micro_price", "long", 0.2, analysis.micro_premium_bps, f"premium={analysis.micro_premium_bps:.1f}bps"))
        elif analysis.micro_premium_bps < -1.0:
            votes.append(_vote("micro_price", "short", 0.2, analysis.micro_premium_bps, f"premium={analysis.micro_premium_bps:.1f}bps"))

    if analysis.ou_zscore is not None:
        if analysis.mean_reversion_signal == "fade_ask":
            votes.append(_vote("ou_mean_reversion", "long", 0.3, analysis.ou_zscore, f"z={analysis.ou_zscore:.2f} fade_ask"))
        elif analysis.mean_reversion_signal == "fade_bid":
            votes.append(_vote("ou_mean_reversion", "short", 0.3, analysis.ou_zscore, f"z={analysis.ou_zscore:.2f} fade_bid"))

    if analysis.momentum_bps > 5:
        votes.append(_vote("momentum", "long", 0.15, analysis.momentum_bps, f"mom={analysis.momentum_bps:.1f}bps"))
    elif analysis.momentum_bps < -5:
        votes.append(_vote("momentum", "short", 0.15, analysis.momentum_bps, f"mom={analysis.momentum_bps:.1f}bps"))

    for r in analysis.reasons:
        if "wall" in r:
            direction = "long" if "bid_walls" in r else "short" if "ask_walls" in r else "flat"
            votes.append(_vote("liquidity_walls", direction, 0.18, None, r))

    if analysis.target_bias == "approach_buy":
        votes.append(_vote("target_price", "long", 0.12, analysis.distance_to_target_pct, "below target"))
    elif analysis.target_bias == "approach_sell":
        votes.append(_vote("target_price", "short", 0.12, analysis.distance_to_target_pct, "above target"))

    long_w = sum(v.weight for v in votes if v.direction == "long")
    short_w = sum(v.weight for v in votes if v.direction == "short")
    net = long_w - short_w
    conf = min(1.0, abs(net) / 0.8) if votes else 0.0

    if kill_switch:
        blockers.append(kill_reason or "kill_switch")
    if analysis.regime == MarketRegime.STRESSED.value:
        blockers.append("regime_stressed")
    if analysis.spread_bps > 20:
        blockers.append(f"wide_spread_{analysis.spread_bps:.1f}bps")
    if sustained is not None and not sustained.ready and not in_position:
        blockers.append(f"sustained:{sustained.reason}")
    if analysis.score < entry_min_score and not in_position:
        blockers.append(f"score_below_{entry_min_score}")

    if in_position:
        action = "hold"
        rationale.append("position_open_manage_exits")
    elif blockers:
        action = "block"
        rationale.extend(blockers)
    elif analysis.score >= entry_min_score and net > 0.15:
        action = "enter_long"
        rationale.append(f"score={analysis.score:.2f} net_vote={net:.2f} conf={conf:.2f}")
        rationale.extend(v.note for v in votes if v.direction == "long")
    else:
        action = "block"
        rationale.append(f"insufficient_edge score={analysis.score:.2f} net={net:.2f}")

    sus_dict = None
    if sustained is not None:
        sus_dict = {
            "ready": sustained.ready,
            "hold_seconds": sustained.hold_seconds,
            "consecutive": sustained.consecutive,
            "avg_score": sustained.avg_score,
            "reason": sustained.reason,
        }

    return DecisionRecord(
        action=action,
        confidence=round(conf, 4),
        regime=analysis.regime,
        score=analysis.score,
        votes=votes,
        blockers=blockers,
        rationale=rationale[:12],
        sustained=sus_dict,
        kelly_fraction=kelly_fraction,
        suggested_notional_usdt=suggested_notional,
    )
