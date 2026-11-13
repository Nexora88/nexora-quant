"""One-shot source fixer: remove double hourly_trade_ts append in engine_tick."""
from __future__ import annotations

from pathlib import Path

_MARKER = "NEXORA_ANTICHURN_APPLIED_v1"


def apply() -> bool:
    path = Path(__file__).resolve().with_name("engine_tick.py")
    text = path.read_text(encoding="utf-8")
    if _MARKER in text:
        return False
    if "hourly_trade_ts = list(getattr(state" not in text:
        path.write_text(text.rstrip() + f"\n\n# {_MARKER}\n", encoding="utf-8")
        return False
    old = (
        "                                state.position_opened_at = time.time()\n"
        "                                state.last_entry_at = time.time()\n"
        "                                try:\n"
        "                                    state.hourly_trade_ts = list(getattr(state, \"hourly_trade_ts\", []) or []) + [time.time()]\n"
        "                                except Exception:\n"
        "                                    pass\n"
    )
    new = "                                # hourly via record_fill only (anti-churn single source)\n"
    text2 = text.replace(old, new)
    old2 = (
        "                            state.position_opened_at = time.time()\n"
        "                            state.last_entry_at = time.time()\n"
        "                            try:\n"
        "                                state.hourly_trade_ts = list(getattr(state, \"hourly_trade_ts\", []) or []) + [time.time()]\n"
        "                            except Exception:\n"
        "                                pass\n"
    )
    new2 = "                            # hourly via record_fill only (anti-churn single source)\n"
    text2 = text2.replace(old2, new2)
    if text2 == text:
        return False
    path.write_text(text2.rstrip() + f"\n\n# {_MARKER}\n", encoding="utf-8")
    return True
