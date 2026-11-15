"""Per-depth-tick trading core.

Body: app/_et_b64/body.z0 + body.z1 (zlib+base64).
Loader wraps handle_tick with TARGET_EQUITY soft-halt and paper milestones.
"""
from __future__ import annotations

import base64
import time
import zlib
from pathlib import Path

_DIR = Path(__file__).resolve().parent / "_et_b64"


def _load_source() -> str:
    z0 = _DIR / "body.z0"
    z1 = _DIR / "body.z1"
    if not z0.is_file() or not z1.is_file():
        raise RuntimeError("Missing app/_et_b64/body.z0 or body.z1")
    b64 = z0.read_text(encoding="ascii").strip() + z1.read_text(encoding="ascii").strip()
    text = zlib.decompress(base64.b64decode(b64.encode("ascii"))).decode("utf-8")
    if "async def handle_tick" not in text:
        raise RuntimeError("Decoded engine_tick body invalid")
    return text


_ns: dict = {"__name__": "app.engine_tick", "__file__": str(Path(__file__).resolve())}
exec(compile(_load_source(), str(Path(__file__).resolve()), "exec"), _ns)
_inner_handle_tick = _ns["handle_tick"]


async def handle_tick(depth, store, history, features, mode, key, persist, confirmations, ticks):
    """Core tick + soft equity goal halt (new entries only; exits still run)."""
    try:
        from app.config import settings
        from app.goal import evaluate_goal, paper_milestones
        from app.engine_setup import state, log

        ex = getattr(state, "executor", None)
        bid = None
        try:
            if depth is not None and getattr(depth, "best_bid", None):
                bid = float(depth.best_bid[0])
        except Exception:
            bid = None
        mark_eq = None
        if ex is not None:
            try:
                snap = ex.snapshot(bid)
                mark_eq = float(snap.get("equity_usdt") or snap.get("cash_usdt") or 0.0)
            except Exception:
                mark_eq = float(getattr(ex, "cash_usdt", 0.0) or 0.0)

        g = evaluate_goal(
            bid=bid,
            equity_usdt=mark_eq,
            target_price=getattr(settings, "target_price", None),
            target_equity_usdt=getattr(settings, "target_equity_usdt", None),
        )
        ms = paper_milestones(
            equity_usdt=mark_eq,
            starting_cash_usdt=float(getattr(settings, "starting_cash_usdt", 100.0) or 100.0),
        )
        state.goal_status = {
            "note": g.note,
            "halt_entries": bool(g.halt_entries),
            "price_hit": bool(g.price_hit),
            "equity_hit": bool(g.equity_hit),
            "equity_usdt": mark_eq,
            "target_equity_usdt": getattr(settings, "target_equity_usdt", None),
            "target_price": getattr(settings, "target_price", None),
            **ms,
        }

        flat = ex is None or float(getattr(ex, "base_quantity", 0) or 0) <= 0
        if g.halt_entries and flat:
            # Saturate hourly anti-churn so body refuses new entries; exits unaffected.
            n = int(getattr(settings, "max_trades_per_hour", 8) or 8) + 2
            now = time.time()
            state.hourly_trade_ts = [now] * n
            bl = list(getattr(state, "blockers_live", None) or [])
            note = f"goal_halt:{g.note}"
            if note not in bl:
                state.blockers_live = [note] + bl[:11]
            if ticks % 60 == 0:
                log.info(
                    "goal soft-halt entries: %s equity=%.2f milestone=%s",
                    g.note,
                    mark_eq or 0.0,
                    ms.get("milestone"),
                )
    except Exception:
        pass

    return await _inner_handle_tick(
        depth, store, history, features, mode, key, persist, confirmations, ticks
    )


__all__ = ["handle_tick"]
