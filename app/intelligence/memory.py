"""Trade memory — never forget PnL lessons; expand pattern knowledge."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class TradeEpisode:
    pnl: float
    regime: str
    structure: str
    motor_bias: str
    reason: str
    score: float
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TradeMemory:
    def __init__(self, *, max_episodes: int = 200, capacity: int | None = None) -> None:
        self.max_episodes = int(capacity if capacity is not None else max_episodes)
        self._episodes: deque[TradeEpisode] = deque(maxlen=self.max_episodes)
        self._stats: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
        self._lifetime_pnl = 0.0
        self._lifetime_n = 0
        self._lifetime_wins = 0

    @staticmethod
    def setup_key(regime: str, structure: str, motor_bias: str) -> str:
        st = (structure or "unk").split("_")[0] if structure else "unk"
        return f"{regime}|{st}|{motor_bias}"

    def remember(
        self,
        pnl: float,
        *,
        regime: str = "unknown",
        structure: str = "unknown",
        motor_bias: str = "neutral",
        reason: str = "",
        score: float = 0.0,
    ) -> None:
        ep = TradeEpisode(
            pnl=float(pnl),
            regime=str(regime),
            structure=str(structure),
            motor_bias=str(motor_bias),
            reason=str(reason)[:64],
            score=float(score),
        )
        self._episodes.append(ep)
        self._lifetime_pnl += ep.pnl
        self._lifetime_n += 1
        if ep.pnl > 0:
            self._lifetime_wins += 1
        key = self.setup_key(ep.regime, ep.structure, ep.motor_bias)
        st = self._stats[key]
        if ep.pnl > 0:
            st[0] += 1
        else:
            st[1] += 1
        st[2] += ep.pnl

    def lesson_for(
        self,
        *,
        regime: str,
        structure: str = "unknown",
        motor_bias: str = "neutral",
    ) -> dict[str, Any]:
        key = self.setup_key(regime, structure, motor_bias)
        st = self._stats.get(key)
        if not st or (st[0] + st[1]) < 2:
            fam_pnl = 0.0
            fam_n = 0
            fam_w = 0
            for k, v in self._stats.items():
                if k.startswith(str(regime) + "|"):
                    fam_pnl += v[2]
                    fam_n += v[0] + v[1]
                    fam_w += v[0]
            if fam_n >= 3:
                fwr = fam_w / fam_n
                if fam_pnl < 0 and fwr < 0.4:
                    return {
                        "key": key,
                        "action": "cautious",
                        "allow": True,
                        "size_mult": 0.7,
                        "note": f"regime_family_weak wr={fwr:.2f} n={int(fam_n)}",
                    }
                if fam_pnl > 0 and fwr >= 0.55:
                    return {
                        "key": key,
                        "action": "explore",
                        "allow": True,
                        "size_mult": 1.1,
                        "note": f"regime_family_strong wr={fwr:.2f} n={int(fam_n)}",
                    }
            return {
                "key": key,
                "action": "explore",
                "allow": True,
                "size_mult": 1.0,
                "note": "no_memory_yet",
            }
        wins, losses, sum_pnl = st
        n = wins + losses
        wr = wins / n
        if sum_pnl < 0 and losses >= 2 and wr < 0.4:
            return {
                "key": key,
                "action": "avoid",
                "allow": False,
                "size_mult": 0.0,
                "note": f"toxic_setup wr={wr:.2f} pnl={sum_pnl:.3f} n={int(n)}",
            }
        if sum_pnl > 0 and wr >= 0.55:
            return {
                "key": key,
                "action": "prefer",
                "allow": True,
                "size_mult": min(1.4, 1.0 + (wr - 0.5)),
                "note": f"proven_setup wr={wr:.2f} pnl={sum_pnl:.3f} n={int(n)}",
            }
        return {
            "key": key,
            "action": "cautious",
            "allow": True,
            "size_mult": 0.85,
            "note": f"mixed_setup wr={wr:.2f} pnl={sum_pnl:.3f} n={int(n)}",
        }

    def recent_lessons(self, n: int = 5) -> list[str]:
        out = []
        for ep in list(self._episodes)[-n:]:
            tag = "WIN" if ep.pnl > 0 else "LOSS"
            out.append(f"{tag} {ep.pnl:+.3f} {ep.regime}/{ep.reason}")
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "lifetime_trades": self._lifetime_n,
            "lifetime_wins": self._lifetime_wins,
            "lifetime_pnl": round(self._lifetime_pnl, 6),
            "episodes": len(self._episodes),
            "setups_known": len(self._stats),
            "recent": self.recent_lessons(5),
            "top_setups": self._top_setups(4),
        }

    def _top_setups(self, k: int) -> list[dict[str, Any]]:
        rows = []
        for key, st in self._stats.items():
            n = st[0] + st[1]
            if n < 1:
                continue
            rows.append({
                "setup": key,
                "wins": int(st[0]),
                "losses": int(st[1]),
                "pnl": round(st[2], 4),
                "wr": round(st[0] / n, 3),
            })
        rows.sort(key=lambda r: r["pnl"], reverse=True)
        return rows[:k]

    def export_state(self) -> dict[str, Any]:
        return {
            "episodes": [
                {
                    "pnl": e.pnl,
                    "regime": e.regime,
                    "structure": e.structure,
                    "motor_bias": e.motor_bias,
                    "reason": e.reason,
                    "score": e.score,
                    "ts": e.ts,
                }
                for e in self._episodes
            ],
            "stats": {k: list(v) for k, v in self._stats.items()},
            "lifetime_pnl": self._lifetime_pnl,
            "lifetime_n": self._lifetime_n,
            "lifetime_wins": self._lifetime_wins,
        }

    def load_state(self, data: dict[str, Any] | None) -> None:
        if not data:
            return
        self._episodes.clear()
        for row in data.get("episodes") or []:
            self._episodes.append(
                TradeEpisode(
                    pnl=float(row.get("pnl", 0)),
                    regime=str(row.get("regime", "unknown")),
                    structure=str(row.get("structure", "unknown")),
                    motor_bias=str(row.get("motor_bias", "neutral")),
                    reason=str(row.get("reason", "")),
                    score=float(row.get("score", 0)),
                    ts=str(row.get("ts", "")),
                )
            )
        self._stats = defaultdict(lambda: [0.0, 0.0, 0.0])
        for k, v in (data.get("stats") or {}).items():
            self._stats[k] = [float(v[0]), float(v[1]), float(v[2])]
        self._lifetime_pnl = float(data.get("lifetime_pnl", 0))
        self._lifetime_n = int(data.get("lifetime_n", 0))
        self._lifetime_wins = int(data.get("lifetime_wins", 0))
