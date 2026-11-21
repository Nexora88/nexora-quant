"""Two-stage multi-symbol router.

Depth scans rank candidates for deeper analysis. Only the full engine's final
pre-order eligibility can authorize an entry; scan scores are never entry signals.
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
    depth_usdt: float = 0.0
    liquid: bool = True
    reasons: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    scan_score: float | None = None
    analysis_confirmed: bool = True
    entry_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "score": self.score,
            "regime": self.regime,
            "spoof_score": self.spoof_score,
            "btc_blocked": self.btc_blocked,
            "tradeable": self.tradeable,
            "depth_usdt": self.depth_usdt,
            "liquid": self.liquid,
            "reasons": list(self.reasons),
            "updated_at": self.updated_at,
            "scan_score": self.scan_score,
            "analysis_confirmed": self.analysis_confirmed,
            "entry_ready": self.entry_ready,
        }


class SymbolRouter:
    """Keeps latest scores per symbol and selects the best entry candidate."""

    def __init__(
        self, *, min_score: float = 0.38, max_spoof: float = 0.60,
        max_age_seconds: float = 8.0,
    ) -> None:
        self.min_score = min_score
        self.max_spoof = max_spoof
        self.max_age_seconds = max(0.1, float(max_age_seconds))
        self._board: dict[str, SymbolScore] = {}
        self.active_symbol: str | None = None

    def _is_fresh(self, row: SymbolScore, now: datetime) -> bool:
        try:
            updated = datetime.fromisoformat(row.updated_at)
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            age = (now - updated.astimezone(timezone.utc)).total_seconds()
            return -5.0 <= age <= self.max_age_seconds
        except (TypeError, ValueError):
            return False

    def update(
        self,
        symbol: str,
        *,
        score: float,
        regime: str = "unknown",
        spoof_score: float = 0.0,
        btc_blocked: bool = False,
        depth_usdt: float = 0.0,
        liquid: bool = True,
        reasons: list[str] | None = None,
    ) -> SymbolScore:
        regime_l = str(regime).lower()
        regime_ok = regime_l not in ("stressed",)
        if regime_l in ("choppy",) and score < self.min_score + 0.08:
            regime_ok = False
        tradeable = (
            score >= self.min_score
            and spoof_score < self.max_spoof
            and not btc_blocked
            and liquid
            and regime_ok
        )
        row = SymbolScore(
            symbol=symbol.lower(),
            score=float(score),
            regime=str(regime),
            spoof_score=float(spoof_score),
            btc_blocked=bool(btc_blocked),
            tradeable=tradeable,
            depth_usdt=float(depth_usdt),
            liquid=bool(liquid),
            reasons=list(reasons or []),
        )
        row.entry_ready = bool(tradeable)
        row.analysis_confirmed = True
        previous = self._board.get(row.symbol)
        if previous is not None:
            row.scan_score = previous.scan_score
        self._board[row.symbol] = row
        return row

    def update_scan(
        self, symbol: str, *, score: float, depth_usdt: float = 0.0,
        liquid: bool = True, reasons: list[str] | None = None,
    ) -> SymbolScore:
        """Store prefilter quality only; a scan can never authorize an entry."""
        key = str(symbol).lower()
        row = SymbolScore(
            symbol=key, score=float(score), regime="scan", spoof_score=0.0,
            btc_blocked=False, tradeable=False, depth_usdt=float(depth_usdt),
            liquid=bool(liquid), reasons=list(reasons or []),
            scan_score=float(score), analysis_confirmed=False, entry_ready=False,
        )
        previous = self._board.get(key)
        if previous is not None and previous.analysis_confirmed and self._is_fresh(previous, datetime.now(timezone.utc)):
            row.score = previous.score
            row.regime = previous.regime
            row.spoof_score = previous.spoof_score
            row.btc_blocked = previous.btc_blocked
            row.tradeable = previous.tradeable
            row.analysis_confirmed = True
            row.entry_ready = previous.entry_ready
            row.reasons = list(previous.reasons)
            # A new scan must not refresh the age of the old full analysis.
            row.updated_at = previous.updated_at
        self._board[key] = row
        return row

    def update_analysis(
        self, symbol: str, *, score: float, regime: str = "unknown",
        spoof_score: float = 0.0, btc_blocked: bool = False,
        depth_usdt: float = 0.0, liquid: bool = True,
        reasons: list[str] | None = None, entry_ready: bool = False,
    ) -> SymbolScore:
        """Record the full engine decision; only this path can make a row selectable."""
        row = self.update(
            symbol, score=score, regime=regime, spoof_score=spoof_score,
            btc_blocked=btc_blocked, depth_usdt=depth_usdt, liquid=liquid,
            reasons=reasons,
        )
        # The full engine's final pre-order eligibility is authoritative here.
        # The scan score and router heuristics must never override that decision.
        row.entry_ready = bool(entry_ready)
        row.tradeable = row.entry_ready
        row.analysis_confirmed = True
        return row

    def leaderboard(self, *, limit: int = 8) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        rows = [
            row for row in self._board.values()
            if self._is_fresh(row, now)
        ]
        rows.sort(key=lambda row: row.score, reverse=True)
        return [row.to_dict() for row in rows[:limit]]

    def select_best(self) -> SymbolScore | None:
        """Prefer a fully analyzed executable candidate; otherwise pick the best untested scan row."""
        now = datetime.now(timezone.utc)
        fresh = [row for row in self._board.values() if self._is_fresh(row, now)]
        approved = [
            row for row in fresh
            if row.analysis_confirmed and row.entry_ready and row.tradeable and row.liquid
        ]
        if approved:
            best = max(approved, key=lambda r: (r.score, r.depth_usdt))
            self.active_symbol = best.symbol
            return best
        pending = [
            row for row in fresh
            if not row.analysis_confirmed
            and row.liquid
            and row.score >= self.min_score
        ]
        if not pending:
            self.active_symbol = None
            return None
        best = max(pending, key=lambda r: (r.scan_score if r.scan_score is not None else r.score, r.depth_usdt))
        self.active_symbol = best.symbol
        return best

    def select_best_entry(self) -> SymbolScore | None:
        """Return only a fresh, full-analysis-approved entry candidate."""
        now = datetime.now(timezone.utc)
        approved = [
            row for row in self._board.values()
            if row.analysis_confirmed and row.entry_ready and row.tradeable
            and row.liquid and self._is_fresh(row, now)
        ]
        if not approved:
            return None
        return max(approved, key=lambda row: (row.score, row.depth_usdt))

    def should_enter_on(self, symbol: str) -> bool:
        best = self.select_best_entry()
        return best is not None and best.symbol == symbol.lower()
