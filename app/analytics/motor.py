"""Multi-model analysis motor: math + kinematics + chart structure + compound.

Stability design:
- Fused score is EMA-smoothed so single noisy L2 ticks do not flip bias.
- Bias uses hysteresis (enter long/short harder than exit to neutral).
- History-consistency vote compares short vs long path *without* requiring
  offline labels — live path only; not a pure lag model.
"""
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
    raw_fused: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fused_score": round(self.fused_score, 4),
            "raw_fused": round(self.raw_fused, 4),
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
            "notes": self.notes[:8],
        }


class AnalysisMotor:
    def __init__(
        self,
        *,
        window: int = 120,
        ema_alpha: float = 0.22,
        enter_threshold: float = 0.22,
        exit_threshold: float = 0.10,
    ) -> None:
        self.window = window
        self.ema_alpha = max(0.05, min(0.9, ema_alpha))
        self.enter_threshold = enter_threshold
        self.exit_threshold = exit_threshold
        self._mids: deque[float] = deque(maxlen=window)
        self._log_rets: deque[float] = deque(maxlen=window)
        self._equity: deque[float] = deque(maxlen=window)
        self._swing_highs: deque[float] = deque(maxlen=8)
        self._swing_lows: deque[float] = deque(maxlen=8)
        self._last_mid = 0.0
        self._compound = 1.0
        self._ema_fused = 0.0
        self._ema_ready = False
        self._bias = "neutral"
        self._ticks = 0

    def push_mid(self, mid: float) -> None:
        if mid <= 0:
            return
        if self._last_mid > 0:
            r = math.log(mid / self._last_mid)
            self._log_rets.append(r)
            self._compound *= math.exp(r)
            if self._compound > 10.0:
                self._compound = 10.0
            elif self._compound < 0.1:
                self._compound = 0.1
        self._mids.append(mid)
        self._last_mid = mid
        self._ticks += 1
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
        long = rets[-min(20, len(rets)) :]
        v = sum(short) / len(short)
        v_long = sum(long) / len(long)
        a = v - v_long
        score = _clamp(v * 500.0 + a * 300.0)
        return ModelVote("kinematics", score, 0.22, f"v={v * 1e4:.2f}bps a={a * 1e4:.2f}bps")

    def _compound_path(self) -> ModelVote:
        rets = list(self._log_rets)
        if len(rets) < 8:
            return ModelVote("compound", 0.0, 0.12, "warming")
        n = min(30, len(rets))
        geo = math.exp(sum(rets[-n:]) / n) - 1.0
        score = _clamp(geo * 800.0)
        return ModelVote("compound", score, 0.15, f"geo={geo * 1e4:.2f}bps n={n}")

    def _chart_structure(self) -> ModelVote:
        highs = list(self._swing_highs)
        lows = list(self._swing_lows)
        if len(highs) < 2 or len(lows) < 2:
            return ModelVote("structure", 0.0, 0.15, "need_swings")
        hh = highs[-1] > highs[-2]
        hl = lows[-1] > lows[-2]
        lh = highs[-1] < highs[-2]
        ll = lows[-1] < lows[-2]
        if hh and hl:
            return ModelVote("structure", 0.7, 0.22, "HH_HL_uptrend")
        if lh and ll:
            return ModelVote("structure", -0.7, 0.22, "LH_LL_downtrend")
        if hh and not hl:
            return ModelVote("structure", 0.25, 0.12, "HH_only")
        if ll and not lh:
            return ModelVote("structure", -0.25, 0.12, "LL_only")
        return ModelVote("structure", 0.0, 0.08, "mixed_structure")

    def _micro_vote(self, *, weighted_obi: float | None, micro_premium_bps: float) -> ModelVote:
        score = 0.0
        parts = []
        if weighted_obi is not None:
            score += _clamp(weighted_obi * 1.5)
            parts.append(f"obi={weighted_obi:.3f}")
        if abs(micro_premium_bps) > 0.1:
            score += _clamp(micro_premium_bps / 15.0)
            parts.append(f"micro={micro_premium_bps:.1f}bps")
        return ModelVote("microstructure", _clamp(score), 0.22, " ".join(parts) or "flat")

    def _regime_vote(self, regime: str) -> ModelVote:
        if regime == "trend":
            return ModelVote("regime", 0.15, 0.08, "trend_ok")
        if regime == "range":
            return ModelVote("regime", 0.0, 0.08, "range_mean_rev_bias")
        if regime == "stressed":
            return ModelVote("regime", -0.5, 0.22, "stressed_pause")
        if regime == "choppy":
            return ModelVote("regime", -0.45, 0.20, "choppy_pause")
        return ModelVote("regime", 0.0, 0.05, regime or "unknown")

    def _history_consistency(self) -> ModelVote:
        """Short path agrees with medium path → confidence; conflict → damp."""
        rets = list(self._log_rets)
        if len(rets) < 16:
            return ModelVote("history", 0.0, 0.08, "warming")
        s = sum(rets[-5:]) / 5
        m = sum(rets[-16:]) / 16
        if s * m > 0 and abs(s) > 1e-6 and abs(m) > 1e-6:
            score = _clamp((abs(s) + abs(m)) * 250.0 * (1.0 if s > 0 else -1.0))
            return ModelVote("history", score, 0.14, "path_agree")
        if s * m < 0:
            return ModelVote(
                "history",
                _clamp(-abs(s - m) * 200.0 * (1 if s > m else -1) * 0.15),
                0.14,
                "path_conflict",
            )
        return ModelVote("history", 0.0, 0.1, "path_flat")

    def _apply_hysteresis(self, fused: float) -> str:
        """Bias sticky until score crosses enter/exit bands."""
        b = self._bias
        if b == "neutral":
            if fused >= self.enter_threshold:
                self._bias = "long"
            elif fused <= -self.enter_threshold:
                self._bias = "short"
        elif b == "long":
            if fused <= -self.enter_threshold:
                self._bias = "short"
            elif fused < self.exit_threshold:
                self._bias = "neutral"
        elif b == "short":
            if fused >= self.enter_threshold:
                self._bias = "long"
            elif fused > -self.exit_threshold:
                self._bias = "neutral"
        return self._bias

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
            self._history_consistency(),
        ]
        wsum = sum(max(v.weight, 1e-9) for v in votes)
        raw = sum(v.score * v.weight for v in votes) / wsum
        if not self._ema_ready:
            self._ema_fused = raw
            self._ema_ready = True
        else:
            a = self.ema_alpha
            self._ema_fused = a * raw + (1.0 - a) * self._ema_fused
        fused = self._ema_fused
        bias = self._apply_hysteresis(fused)

        rets = list(self._log_rets)
        v = (sum(rets[-5:]) / 5) if len(rets) >= 5 else 0.0
        v_long = (sum(rets[-20:]) / min(20, len(rets))) if rets else 0.0
        acc = v - v_long if rets else 0.0
        n = min(30, len(rets)) if rets else 0
        geo = (math.exp(sum(rets[-n:]) / n) - 1.0) if n else 0.0
        structure = next((x.detail for x in votes if x.name == "structure"), "unknown")
        notes = [f"{x.name}:{x.score:+.2f}" for x in votes]
        notes.append(f"ema={fused:+.3f} raw={raw:+.3f}")
        return MotorReport(
            fused_score=fused,
            bias=bias,
            votes=votes,
            velocity=v,
            acceleration=acc,
            geo_mean_bps=geo * 1e4,
            structure=structure,
            compound_factor=self._compound,
            raw_fused=raw,
            notes=notes,
        )

    def export_state(self) -> dict[str, Any]:
        return {
            "ema_fused": self._ema_fused,
            "ema_ready": self._ema_ready,
            "bias": self._bias,
            "compound": self._compound,
            "last_mid": self._last_mid,
            "ticks": self._ticks,
            "mids": list(self._mids)[-40:],
            "log_rets": list(self._log_rets)[-40:],
        }

    def load_state(self, data: dict[str, Any] | None) -> None:
        if not data:
            return
        self._ema_fused = float(data.get("ema_fused", 0.0) or 0.0)
        self._ema_ready = bool(data.get("ema_ready", False))
        self._bias = str(data.get("bias") or "neutral")
        if self._bias not in ("long", "short", "neutral"):
            self._bias = "neutral"
        self._compound = float(data.get("compound", 1.0) or 1.0)
        self._last_mid = float(data.get("last_mid", 0.0) or 0.0)
        self._ticks = int(data.get("ticks", 0) or 0)
        for mid in data.get("mids") or []:
            try:
                m = float(mid)
            except (TypeError, ValueError):
                continue
            if m > 0:
                self._mids.append(m)
        for r in data.get("log_rets") or []:
            try:
                self._log_rets.append(float(r))
            except (TypeError, ValueError):
                continue
        self._update_swings()
