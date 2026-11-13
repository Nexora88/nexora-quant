"""Session expectancy + maker stats helpers mixed into RuntimeState."""
from __future__ import annotations

from typing import Any


def session_expectancy(self) -> dict[str, Any]:
    """Fee-net expectancy from closed sells in recent_fills (session window)."""
    sells = [
        f
        for f in list(self.recent_fills)
        if str(f.get("side") or "").lower() in {"sell", "short"}
    ]
    if not sells:
        return {
            "n": 0,
            "expectancy_usdt": None,
            "win_rate": None,
            "sum_pnl_usdt": 0.0,
            "avg_win_usdt": None,
            "avg_loss_usdt": None,
        }
    pnls = [float(f.get("pnl_usdt") or 0.0) for f in sells]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    n = len(pnls)
    return {
        "n": n,
        "expectancy_usdt": round(sum(pnls) / n, 4),
        "win_rate": round(len(wins) / n, 3),
        "sum_pnl_usdt": round(sum(pnls), 4),
        "avg_win_usdt": round(sum(wins) / len(wins), 4) if wins else None,
        "avg_loss_usdt": round(sum(losses) / len(losses), 4) if losses else None,
    }


def maker_stats(self) -> dict[str, Any]:
    attempts = int(getattr(self, "maker_entry_attempts", 0) or 0)
    fills = int(getattr(self, "maker_entry_fills", 0) or 0)
    timeouts = int(getattr(self, "maker_entry_timeouts", 0) or 0)
    fill_rate = round(fills / attempts, 3) if attempts else None
    timeout_rate = round(timeouts / attempts, 3) if attempts else None
    return {
        "attempts": attempts,
        "fills": fills,
        "timeouts": timeouts,
        "fill_rate": fill_rate,
        "timeout_rate": timeout_rate,
        "weak_maker_path": bool(timeout_rate is not None and timeout_rate > 0.30),
    }


def install_state_metrics(cls: type) -> type:
    """Attach metrics helpers onto RuntimeState class."""
    cls.session_expectancy = session_expectancy  # type: ignore[attr-defined]
    cls.maker_stats = maker_stats  # type: ignore[attr-defined]
    return cls
