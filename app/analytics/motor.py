"""Multi-model analysis motor: math + kinematics + chart structure + compound."""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass(slots=True)
class ModelVote:
    name: str
    score: float
    weight: float
    detail: str


@dataclass(slots=True)
class MotorReport:
    fused_score: float
    bias: str
    votes: list[ModelVote] = field(default_factory=list)
    velocity: float = 0.0
    acceleration: float = 0.0
    geo_mean_bps: float = 0.0
    structure: str = "unknown"
    compound_factor: float = 1.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fused_score": round(self.fused_score, 4),
            "bias": self.bias,
            "velocity": round(self.velocity, 6),
            "acceleration": round(self.acceleration, 6),
            "geo_mean_bps": round(self.geo_mean_bps, 3),
            "structure": self.structure,
            "compound_factor": round(self.compound_factor, 6),
            "votes": [
                {"name": v.name, "score": round(v.score, 3), "weight": v.weight, "detail": v.detail}
                for v in self.votes
            ],
            "notes": self.notes[:6],
        }


class AnalysisMotor:
    def __init__(self, *, window: int = 120) -> None:
        self.window = window
        self._mids: deque[float] = deque(maxlen=window)
        self._log_rets: deque[float] = deque(maxlen=window)
        self._equity: deque[float] = deque(maxlen=window)
        self._swing_highs: deque[float] = deque(maxlen=8)
        self._swing_lows: deque[float] = deque(maxlen=8)
        self._last_mid = 0.0
        self._compound = 1.0

    def push_mid(self, mid: float) -> None:
        if mid <= 0:
            return
        if self._last_mid > 0:
            r = math.log(mid / self._last_mid)
            self._log_rets.append(r)
            self._compound *= math.exp(r)
        self._mids.append(mid)
        self._last_mid = mid
        self._update_swings()

    def push_equity(self, equity: float) -> None:
        if equity > 0:
            self._equity.append(equity)

    def _update_swings(self) -> None:
        mids = list(self._mids)
        if len(mids) < 5:
            return
        a, b, c, d, e = mids[-5:]
        if c >= a and c >= b and c >= d and c >= e:
            self._swing_highs.append(c)
        if c <= a and c <= b and c <= d and c <= e:
            self._swing_lows.append(c)

    def _kinematics(self) -> ModelVote:
        rets = list(self._log_rets)
        if len(rets) < 6:
            return ModelVote("kinematics", 0.0, 0.2, "warming")
        short = rets[-5:]
        long = rets[-min(20, len(rets)):]
        v = sum(short) / len(short)
        v_long = sum(long) / len(long)
        a = v - v_long
        score = _clamp(v * 500.0 + a * 300.0)
        return ModelVote("kinematics", score, 0.25, f"v={v*1e4:.2f}bps a={a*1e4:.2f}bps")

    def _compound_path(self) -> ModelVote:
        rets = list(self._log_rets)
        if len(rets) < 8:
            return ModelVote("compound", 0.0, 0.15, "warming")
        n = min(30, len(rets))
        geo = math.exp(sum(rets[-n:]) / n) - 1.0
        score = _clamp(geo * 800.0)
        return ModelVote("compound", score, 0.2, f"geo={geo*1e4:.2f}bps n={n}")

    def _chart_structure(self) -> ModelVote:
        highs = list(self._swing_highs)
        lows = list(self._swing_lows)
        if len(highs) < 2 or len(lows) < 2:
            return ModelVote("structure", 0.0, 0.2, "need_swings")
        hh = highs[-1] > highs[-2]
        hl = lows[-1] > lows[-2]
        lh = highs[-1] < highs[-2]
        ll = lows[-1] < lows[-2]
        if hh and hl:
            return ModelVote("structure", 0.7, 0.25, "HH_HL_uptrend")
        if lh and ll:
            return ModelVote("structure", -0.7, 0.25, "LH_LL_downtrend")
        if hh and not hl:
            return ModelVote("structure", 0.25, 0.15, "HH_only")
        if ll and not lh:
            return ModelVote("structure", -0.25, 0.15, "LL_only")
        return ModelVote("structure", 0.0, 0.1, "mixed_structure")

    def _micro_vote(self, *, weighted_obi: float | None, micro_premium_bps: float) -> ModelVote:
        score = 0.0
        parts = []
        if weighted_obi is not None:
            score += _clamp(weighted_obi * 1.5)
            parts.append(f"obi={weighted_obi:.3f}")
        if abs(micro_premium_bps) > 0.1:
            score += _clamp(micro_premium_bps / 15.0)
            parts.append(f"micro={micro_premium_bps:.1f}bps")
        return ModelVote("microstructure", _clamp(score), 0.25, " ".join(parts) or "flat")

    def _regime_vote(self, regime: str) -> ModelVote:
        if regime == "trend":
            return ModelVote("regime", 0.15, 0.1, "trend_ok")
        if regime == "range":
            return ModelVote("regime", 0.0, 0.1, "range_mean_rev_bias")
        if regime == "stressed":
            return ModelVote("regime", -0.5, 0.2, "stressed_penalize")
        return ModelVote("regime", 0.0, 0.05, regime or "unknown")

    def evaluate(
        self,
        *,
        weighted_obi: float | None = None,
        micro_premium_bps: float = 0.0,
        regime: str = "unknown",
    ) -> MotorReport:
        votes = [
            self._kinematics(),
            self._compound_path(),
            self._chart_structure(),
            self._micro_vote(weighted_obi=weighted_obi, micro_premium_bps=micro_premium_bps),
            self._regime_vote(regime),
        ]
        wsum = sum(max(v.weight, 1e-9) for v in votes)
        fused = sum(v.score * v.weight for v in votes) / wsum
        if fused > 0.18:
            bias = "long"
        elif fused < -0.18:
            bias = "short"
        else:
            bias = "neutral"
        rets = list(self._log_rets)
        v = (sum(rets[-5:]) / 5) if len(rets) >= 5 else 0.0
        v_long = (sum(rets[-20:]) / min(20, len(rets))) if rets else 0.0
        a = v - v_long if rets else 0.0
        n = min(30, len(rets)) if rets else 0
        geo = (math.exp(sum(rets[-n:]) / n) - 1.0) if n else 0.0
        structure = next((v.detail for v in votes if v.name == "structure"), "unknown")
        notes = [f"{v.name}:{v.score:+.2f}" for v in votes]
        return MotorReport(
            fused_score=fused, bias=bias, votes=votes,
            velocity=v, acceleration=a, geo_mean_bps=geo * 1e4,
            structure=structure, compound_factor=self._compound, notes=notes,
        )
