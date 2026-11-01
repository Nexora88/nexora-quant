"""Compound growth learner with anti-overfit guards.

Live weights adapt from closed trades, but:
- optional freeze (backtest / research parity)
- anomaly outliers do not yank gates (whale wick / one-off PnL)
- per-update step clamps + L2 pull to prior
- regime change soft-resets toward base (not hard rewrite)

Backtests that freeze the learner stay comparable to a fixed-weight bot.
Live paper may diverge — that is intentional and documented.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class LearnerSnapshot:
    trades: int
    wins: int
    win_rate: float
    avg_pnl: float
    total_pnl: float
    entry_min_score: float
    size_bias: float
    tp_scale: float
    prefer_regime: str
    growth_mode: str
    compound_fraction: float
    note: str
    updated_at: str


class OnlineLearner:
    def __init__(
        self,
        *,
        window: int = 40,
        base_entry_min: float = 0.32,
        min_entry: float = 0.22,
        max_entry: float = 0.65,
        base_compound: float = 0.85,
        l2_lambda: float = 0.08,
        frozen: bool = False,
        min_trades_before_adapt: int = 3,
        anomaly_z: float = 3.0,
        max_entry_step: float = 0.04,
        max_size_step: float = 0.10,
    ) -> None:
        self.window = window
        self.base_entry_min = base_entry_min
        self.min_entry = min_entry
        self.max_entry = max_entry
        self.base_compound = base_compound
        self.l2_lambda = max(0.0, min(0.5, float(l2_lambda)))
        self.frozen = bool(frozen)
        self.min_trades_before_adapt = max(1, int(min_trades_before_adapt))
        self.anomaly_z = max(1.5, float(anomaly_z))
        self.max_entry_step = max(0.005, float(max_entry_step))
        self.max_size_step = max(0.02, float(max_size_step))
        self._last_regime = "unknown"
        self._pnls: deque[float] = deque(maxlen=window)
        self._regimes: deque[str] = deque(maxlen=window)
        self._reasons: deque[str] = deque(maxlen=window)
        self._entry_min = base_entry_min
        self._size_bias = 1.0
        self._tp_scale = 0.9
        self._compound = base_compound
        self._prefer = "any"
        self._growth = "rebuild"
        self._note = "cold_start_compound"
        self._total_pnl = 0.0
        self._lifetime_trades = 0
        self._lifetime_wins = 0
        self._anomaly_skips = 0
        self._production: dict[str, float] | None = None

    def freeze(self, on: bool = True) -> None:
        """When frozen, PnL is still logged but gates/weights do not move."""
        self.frozen = bool(on)
        if on:
            self._note = "frozen_weights"
            self.snapshot_production()

    def snapshot_production(self) -> dict[str, float]:
        """Lock a production weight set for parity checks / backtest compare."""
        self._production = {
            "entry_min": float(self._entry_min),
            "size_bias": float(self._size_bias),
            "tp_scale": float(self._tp_scale),
            "compound": float(self._compound),
        }
        return dict(self._production)

    def restore_production(self) -> None:
        if not self._production:
            return
        self._entry_min = float(self._production["entry_min"])
        self._size_bias = float(self._production["size_bias"])
        self._tp_scale = float(self._production["tp_scale"])
        self._compound = float(self._production["compound"])
        self._note = "restored_production_weights"

    def _is_anomaly(self, pnl: float) -> bool:
        """Reject single-trade overfit from whale wicks / outsized PnL."""
        if len(self._pnls) < 5:
            return False
        xs = list(self._pnls)
        mean = sum(xs) / len(xs)
        var = sum((x - mean) ** 2 for x in xs) / len(xs)
        std = var ** 0.5
        if std < 1e-9:
            return abs(pnl) > max(0.5, 5.0 * (abs(mean) + 0.05))
        return abs(pnl - mean) > self.anomaly_z * std

    def _clamp_steps(
        self,
        *,
        prev_entry: float,
        prev_size: float,
        prev_tp: float,
        prev_comp: float,
    ) -> None:
        def _step(cur: float, prev: float, cap: float) -> float:
            d = cur - prev
            if d > cap:
                return prev + cap
            if d < -cap:
                return prev - cap
            return cur

        self._entry_min = _step(self._entry_min, prev_entry, self.max_entry_step)
        self._size_bias = _step(self._size_bias, prev_size, self.max_size_step)
        self._tp_scale = _step(self._tp_scale, prev_tp, 0.08)
        self._compound = _step(self._compound, prev_comp, 0.06)
        self._entry_min = min(self.max_entry, max(self.min_entry, self._entry_min))
        self._size_bias = min(1.6, max(0.4, self._size_bias))
        self._tp_scale = min(1.25, max(0.55, self._tp_scale))
        self._compound = min(0.95, max(0.5, self._compound))

    def record_trade(self, pnl_usdt: float, *, regime: str = "unknown", reason: str = "") -> None:
        p = float(pnl_usdt)
        anomaly = self._is_anomaly(p)
        self._lifetime_trades += 1
        if p > 0:
            self._lifetime_wins += 1
        self._total_pnl += p

        if self.frozen:
            self._note = f"frozen_skip_adapt pnl={p:.4f}"
            return

        if anomaly:
            self._anomaly_skips += 1
            self._note = f"anomaly_skip pnl={p:.4f} z>{self.anomaly_z:.1f}"
            return

        self._pnls.append(p)
        self._regimes.append(str(regime or "unknown"))
        self._reasons.append(str(reason or "")[:48])

        reg = str(regime or "unknown")
        prev_entry, prev_size = self._entry_min, self._size_bias
        prev_tp, prev_comp = self._tp_scale, self._compound

        if reg != self._last_regime and self._lifetime_trades > 3:
            lam = self.l2_lambda
            self._entry_min = (1 - lam) * self._entry_min + lam * self.base_entry_min
            self._size_bias = (1 - lam) * self._size_bias + lam * 1.0
            self._tp_scale = (1 - lam) * self._tp_scale + lam * 0.9
            self._compound = (1 - lam) * self._compound + lam * self.base_compound
            self._note = f"regime_l2 {self._last_regime}->{reg} lam={lam:.2f}"
            self._growth = "rebuild"
        self._last_regime = reg

        if len(self._pnls) >= self.min_trades_before_adapt:
            self._recompute()
            self._clamp_steps(
                prev_entry=prev_entry,
                prev_size=prev_size,
                prev_tp=prev_tp,
                prev_comp=prev_comp,
            )
        else:
            self._note = f"warming n={len(self._pnls)}"
            self._growth = "rebuild"

    def _recompute(self) -> None:
        n = len(self._pnls)
        if n < 2:
            self._note = f"warming n={n}"
            self._growth = "rebuild"
            return
        wins = sum(1 for x in self._pnls if x > 0)
        wr = wins / n
        avg = sum(self._pnls) / n
        total = sum(self._pnls)
        if wr >= 0.52 and avg > 0 and total > 0:
            self._growth = "grow"
            self._entry_min = max(self.min_entry, self._entry_min - 0.02)
            self._size_bias = min(1.6, self._size_bias + 0.05)
            self._tp_scale = max(0.65, min(1.1, self._tp_scale - 0.02))
            self._compound = min(0.95, self._compound + 0.02)
            self._note = f"compound_grow wr={wr:.2f} avg={avg:.3f}"
        elif wr < 0.38 or total < -abs(avg) * 2:
            self._growth = "protect"
            self._entry_min = min(self.max_entry, self._entry_min + 0.03)
            self._size_bias = max(0.4, self._size_bias - 0.08)
            self._tp_scale = min(1.2, self._tp_scale + 0.03)
            self._compound = max(0.5, self._compound - 0.05)
            self._note = f"protect wr={wr:.2f} avg={avg:.3f}"
        else:
            self._growth = "rebuild"
            self._entry_min = 0.75 * self._entry_min + 0.25 * self.base_entry_min
            self._size_bias = 0.85 * self._size_bias + 0.15 * 1.0
            self._tp_scale = 0.85 * self._tp_scale + 0.15 * 0.9
            self._compound = 0.85 * self._compound + 0.15 * self.base_compound
            self._note = f"rebuild wr={wr:.2f} avg={avg:.3f}"
        lam = self.l2_lambda * 0.25
        self._entry_min = (1 - lam) * self._entry_min + lam * self.base_entry_min
        self._size_bias = (1 - lam) * self._size_bias + lam * 1.0
        by: dict[str, float] = {}
        for p, r in zip(self._pnls, self._regimes):
            by[r] = by.get(r, 0.0) + p
        if by:
            best = max(by.items(), key=lambda kv: kv[1])
            if best[1] > 0 and best[0] not in ("unknown", "stressed"):
                self._prefer = best[0]
            else:
                self._prefer = "any"
        win_reasons = [r for p, r in zip(self._pnls, self._reasons) if p > 0 and r]
        if len(win_reasons) >= 3:
            tp_hits = sum(1 for r in win_reasons if "take_profit" in r)
            if tp_hits / len(win_reasons) >= 0.5:
                self._tp_scale = max(0.6, self._tp_scale - 0.01)
                self._note += " recycle_fast"

    def observe_market(
        self,
        *,
        score: float,
        regime: str,
        flow_pressure: float = 0.0,
        flow_ready: bool = False,
        in_position: bool = False,
    ) -> None:
        if self.frozen:
            return
        sc = float(score)
        reg = str(regime or "unknown")
        self._last_regime = reg
        if not in_position and flow_ready and abs(float(flow_pressure)) >= 0.15:
            if sc >= self._entry_min:
                self._entry_min = max(self.min_entry, self._entry_min - 0.005)
                if reg not in ("unknown", "stressed"):
                    self._prefer = reg if self._prefer in ("any", reg) else self._prefer
                self._note = f"idle_flow_ready score={sc:.2f} reg={reg}"
            elif sc < self._entry_min - 0.1:
                self._entry_min = min(self.max_entry, self._entry_min + 0.002)
                self._note = f"idle_weak_score score={sc:.2f}"
        if in_position:
            return
        if self._lifetime_trades == 0:
            self._entry_min = min(
                self.max_entry,
                max(self.min_entry, 0.9 * self._entry_min + 0.1 * self.base_entry_min),
            )

    @property
    def entry_min_score(self) -> float:
        return float(self._entry_min)

    @property
    def size_bias(self) -> float:
        return float(self._size_bias)

    @property
    def tp_scale(self) -> float:
        return float(self._tp_scale)

    @property
    def compound_fraction(self) -> float:
        return float(self._compound)

    @property
    def prefer_regime(self) -> str:
        return self._prefer

    @property
    def growth_mode(self) -> str:
        return self._growth

    def allows_regime(self, regime: str) -> bool:
        if self._growth == "protect" and regime == "stressed":
            return False
        if self._prefer == "any":
            return True
        if regime == "stressed":
            return False
        return regime == self._prefer or regime == "unknown"

    def snapshot(self) -> LearnerSnapshot:
        n = len(self._pnls)
        wins = sum(1 for x in self._pnls if x > 0)
        avg = (sum(self._pnls) / n) if n else 0.0
        total = sum(self._pnls) if n else 0.0
        return LearnerSnapshot(
            trades=n,
            wins=wins,
            win_rate=(wins / n) if n else 0.0,
            avg_pnl=avg,
            total_pnl=total,
            entry_min_score=self._entry_min,
            size_bias=self._size_bias,
            tp_scale=self._tp_scale,
            prefer_regime=self._prefer,
            growth_mode=self._growth,
            compound_fraction=self._compound,
            note=self._note,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_dict(self) -> dict[str, Any]:
        s = self.snapshot()
        return {
            "trades": s.trades,
            "wins": s.wins,
            "win_rate": s.win_rate,
            "avg_pnl": s.avg_pnl,
            "total_pnl": s.total_pnl,
            "entry_min_score": s.entry_min_score,
            "size_bias": s.size_bias,
            "tp_scale": s.tp_scale,
            "prefer_regime": s.prefer_regime,
            "growth_mode": s.growth_mode,
            "compound_fraction": s.compound_fraction,
            "note": s.note,
            "updated_at": s.updated_at,
            "lifetime_trades": self._lifetime_trades,
            "lifetime_wins": self._lifetime_wins,
            "lifetime_pnl": round(self._total_pnl, 6),
            "frozen": self.frozen,
            "anomaly_skips": self._anomaly_skips,
        }

    def export_state(self) -> dict[str, Any]:
        return {
            "pnls": list(self._pnls),
            "regimes": list(self._regimes),
            "reasons": list(self._reasons),
            "entry_min": self._entry_min,
            "size_bias": self._size_bias,
            "tp_scale": self._tp_scale,
            "compound": self._compound,
            "prefer": self._prefer,
            "growth": self._growth,
            "total_pnl": self._total_pnl,
            "lifetime_trades": self._lifetime_trades,
            "lifetime_wins": self._lifetime_wins,
            "frozen": self.frozen,
            "anomaly_skips": self._anomaly_skips,
            "production": dict(self._production) if self._production else None,
        }

    def load_state(self, data: dict[str, Any] | None) -> None:
        if not data:
            return
        self._pnls = deque((float(x) for x in data.get("pnls") or []), maxlen=self.window)
        self._regimes = deque((str(x) for x in data.get("regimes") or []), maxlen=self.window)
        self._reasons = deque((str(x) for x in data.get("reasons") or []), maxlen=self.window)
        self._entry_min = float(data.get("entry_min", self.base_entry_min))
        self._size_bias = float(data.get("size_bias", 1.0))
        self._tp_scale = float(data.get("tp_scale", 0.9))
        self._compound = float(data.get("compound", self.base_compound))
        self._prefer = str(data.get("prefer", "any"))
        self._growth = str(data.get("growth", "rebuild"))
        self._total_pnl = float(data.get("total_pnl", 0.0))
        self._lifetime_trades = int(data.get("lifetime_trades", 0))
        self._lifetime_wins = int(data.get("lifetime_wins", 0))
        self.frozen = bool(data.get("frozen", False))
        self._anomaly_skips = int(data.get("anomaly_skips", 0))
        prod = data.get("production")
        self._production = dict(prod) if isinstance(prod, dict) else None
        if self._pnls and not self.frozen:
            self._recompute()
