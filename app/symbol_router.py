"""Autonomous multi-symbol ranking: which coin to trade right now.

Watches SYMBOL + SYMBOLS, scores each motor snapshot, and picks the strongest
tradeable candidate. Live mode still executes only the configured primary
unless AUTONOMOUS_SYMBOL is enabled (paper-friendly by default).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class SymbolScore:
    symbol: str
    score: float
    regime: str
    spoof_score: float
    btc_blocked: bool
    tradeable: bool
    reasons: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "score": self.score,
            "regime": self.regime,
            "spoof_score": self.spoof_score,
            "btc_blocked": self.btc_blocked,
            "tradeable": self.tradeable,
            "reasons": list(self.reasons),
            "updated_at": self.updated_at,
        }


class SymbolRouter:
    """Keeps latest scores per symbol and selects the best entry candidate."""

    def __init__(self, *, min_score: float = 0.55, max_spoof: float = 0.55) -> None:
        self.min_score = min_score
        self.max_spoof = max_spoof
        self._board: dict[str, SymbolScore] = {}
        self.active_symbol: str | None = None

    def update(
        self,
        symbol: str,
        *,
        score: float,
        regime: str = "unknown",
        spoof_score: float = 0.0,
        btc_blocked: bool = False,
        reasons: list[str] | None = None,
    ) -> SymbolScore:
        tradeable = (
            score >= self.min_score
            and spoof_score < self.max_spoof
            and not btc_blocked
            and regime not in ("choppy", "stressed", "CHOPPY", "STRESSED")
        )
        row = SymbolScore(
            symbol=symbol.lower(),
            score=float(score),
            regime=str(regime),
            spoof_score=float(spoof_score),
            btc_blocked=bool(btc_blocked),
            tradeable=tradeable,
            reasons=list(reasons or []),
        )
        self._board[row.symbol] = row
        return row

    def leaderboard(self, *, limit: int = 8) -> list[dict[str, Any]]:
        rows = sorted(self._board.values(), key=lambda r: r.score, reverse=True)
        return [r.to_dict() for r in rows[:limit]]

    def select_best(self) -> SymbolScore | None:
        tradeable = [r for r in self._board.values() if r.tradeable]
        if not tradeable:
            self.active_symbol = None
            return None
        best = max(tradeable, key=lambda r: r.score)
        self.active_symbol = best.symbol
        return best

    def should_enter_on(self, symbol: str) -> bool:
        """True if this symbol is currently the top tradeable candidate."""
        best = self.select_best()
        return best is not None and best.symbol == symbol.lower()
