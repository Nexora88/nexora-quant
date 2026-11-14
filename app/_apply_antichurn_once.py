"""One-shot source fixer for engine_tick (anti-churn + maker metrics).

Runs before handle_tick import. Idempotent via marker.
"""
from __future__ import annotations

from pathlib import Path

_MARKER = "NEXORA_ANTICHURN_APPLIED_v2"


def apply() -> bool:
    path = Path(__file__).resolve().with_name("engine_tick.py")
    text = path.read_text(encoding="utf-8")
    if _MARKER in text:
        return False
    changed = False

    # --- anti-churn: remove double hourly append (paper + live) ---
    if "hourly_trade_ts = list(getattr(state" in text:
        old = (
            "                                state.position_opened_at = time.time()\n"
            "                                state.last_entry_at = time.time()\n"
            "                                try:\n"
            "                                    state.hourly_trade_ts = list(getattr(state, \"hourly_trade_ts\", []) or []) + [time.time()]\n"
            "                                except Exception:\n"
            "                                    pass\n"
        )
        new = "                                # hourly via record_fill only (anti-churn single source)\n"
        if old in text:
            text = text.replace(old, new)
            changed = True
        old2 = (
            "                            state.position_opened_at = time.time()\n"
            "                            state.last_entry_at = time.time()\n"
            "                            try:\n"
            "                                state.hourly_trade_ts = list(getattr(state, \"hourly_trade_ts\", []) or []) + [time.time()]\n"
            "                            except Exception:\n"
            "                                pass\n"
        )
        new2 = "                            # hourly via record_fill only (anti-churn single source)\n"
        if old2 in text:
            text = text.replace(old2, new2)
            changed = True

    # --- maker metrics if missing ---
    if "maker_entry_timeouts" not in text:
        paper_old = (
            "                                state.record_fill(trade)\n"
            "                                state.peak_price = entry_px\n"
        )
        paper_new = (
            "                                state.record_fill(trade)\n"
            "                                if prefer_maker:\n"
            "                                    try:\n"
            "                                        state.maker_entry_attempts = int(getattr(state, \"maker_entry_attempts\", 0) or 0) + 1\n"
            "                                        state.maker_entry_fills = int(getattr(state, \"maker_entry_fills\", 0) or 0) + 1\n"
            "                                    except Exception:\n"
            "                                        pass\n"
            "                                state.peak_price = entry_px\n"
        )
        if paper_old in text:
            text = text.replace(paper_old, paper_new, 1)
            changed = True
        live_old = (
            "                            except Exception:\n"
            "                                log.exception(\"buy_limit failed; no market fallback this tick\")\n"
            "                                trade = None\n"
            "                        if trade is None and not prefer_maker:\n"
        )
        live_new = (
            "                            except Exception:\n"
            "                                log.exception(\"buy_limit failed; no market fallback this tick\")\n"
            "                                trade = None\n"
            "                            try:\n"
            "                                state.maker_entry_attempts = int(getattr(state, \"maker_entry_attempts\", 0) or 0) + 1\n"
            "                                if trade:\n"
            "                                    state.maker_entry_fills = int(getattr(state, \"maker_entry_fills\", 0) or 0) + 1\n"
            "                                else:\n"
            "                                    state.maker_entry_timeouts = int(getattr(state, \"maker_entry_timeouts\", 0) or 0) + 1\n"
            "                            except Exception:\n"
            "                                pass\n"
            "                        if trade is None and not prefer_maker:\n"
        )
        if live_old in text:
            text = text.replace(live_old, live_new, 1)
            changed = True

    # strip old v1 marker if present
    text = text.replace("\n# NEXORA_ANTICHURN_APPLIED_v1\n", "\n")
    text = text.rstrip() + f"\n\n# {_MARKER}\n"
    path.write_text(text, encoding="utf-8")
    return changed
