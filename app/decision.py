"""Decision layer: fuse microstructure, regime, walls, sustained into audited choice."""
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
    edge_tradeable: bool | None = None,
    edge_notes: list[str] | None = None,
    adverse_toxic: bool = False,
    adverse_reasons: list[str] | None = None,
    noise_noisy: bool = False,
    noise_reason: str | None = None,
    whale_side: str | None = None,
    whale_strength: float = 0.0,
    whale_note: str | None = None,
    autonomous_mode: bool = False,
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
            votes.append(_vote("ou_mean_reversion", "long", 0.3, analysis.ou_zscore, f"z={analysis.ou_zscore:.2f}"))
        elif analysis.mean_reversion_signal == "fade_bid":
            votes.append(_vote("ou_mean_reversion", "short", 0.3, analysis.ou_zscore, f"z={analysis.ou_zscore:.2f}"))

    if analysis.momentum_bps > 5:
        votes.append(_vote("momentum", "long", 0.15, analysis.momentum_bps, f"mom={analysis.momentum_bps:.1f}bps"))
    elif analysis.momentum_bps < -5:
        votes.append(_vote("momentum", "short", 0.15, analysis.momentum_bps, f"mom={analysis.momentum_bps:.1f}bps"))

    for r in analysis.reasons:
        if "wall" in r:
            direction = "long" if "bid_walls" in r else "short" if "ask_walls" in r else "flat"
            votes.append(_vote("liquidity_walls", direction, 0.18, None, r))

    if whale_side == "bid" and whale_strength >= 0.3:
        votes.append(_vote("whale_bid", "long", 0.22, whale_strength, whale_note or "whale_bid"))
    elif whale_side == "ask" and whale_strength >= 0.3:
        votes.append(_vote("whale_ask", "short", 0.22, whale_strength, whale_note or "whale_ask"))

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

    if edge_tradeable is False:
        if autonomous_mode:
            rationale.append("edge_soft:" + (edge_notes[0] if edge_notes else "low"))
        else:
            blockers.append("edge_quality_insufficient")
            if edge_notes:
                rationale.extend(edge_notes[:3])
    if adverse_toxic:
        if autonomous_mode:
            rationale.append("adverse_soft:" + (adverse_reasons[0] if adverse_reasons else "toxic"))
        else:
            blockers.append("adverse_selection")
            if adverse_reasons:
                rationale.extend(adverse_reasons[:3])
    if noise_noisy:
        if autonomous_mode:
            rationale.append("noise_soft:" + (noise_reason or "noisy"))
        else:
            blockers.append("noise_filter")
            if noise_reason:
                rationale.append(noise_reason)
    if autonomous_mode and sustained is not None and not sustained.ready and not in_position:
        blockers[:] = [b for b in blockers if not str(b).startswith("sustained:")]
        rationale.append("sustained_soft:" + sustained.reason)

    if in_position:
        action = "hold"
        rationale.append("position_open_manage_exits")
    elif blockers:
        action = "block"
        rationale.extend(blockers)
    elif analysis.score >= entry_min_score and net > (0.05 if autonomous_mode else 0.15):
        action = "enter_long"
        rationale.append(f"score={analysis.score:.2f} net_vote={net:.2f}")
        rationale.extend(analysis.reasons[:4])
    else:
        action = "block"
        rationale.append("insufficient_edge")

    return DecisionRecord(
        action=action,
        confidence=round(conf, 3),
        regime=analysis.regime,
        score=analysis.score,
        votes=votes,
        blockers=blockers,
        rationale=rationale[:8],
        sustained=(
            {
                "ready": sustained.ready,
                "hold_seconds": round(sustained.hold_seconds, 2),
                "consecutive": sustained.consecutive,
                "avg_score": round(sustained.avg_score, 3),
                "reason": sustained.reason,
            }
            if sustained
            else None
        ),
        kelly_fraction=kelly_fraction,
        suggested_notional_usdt=suggested_notional,
    )
