#!/usr/bin/env python3
"""Restore app/engine_tick.py from git object 7a4ee79 and apply profit-path patches.

Run from repo root:
  python scripts/restore_engine_tick.py
  git add app/engine_tick.py .env.example docs/PROFIT_PATH.md
  git commit -m "fix: restore engine_tick + profit path"
  git push origin main
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "app" / "engine_tick.py"
GOOD_SHA = "7a4ee79d74fbf286eac46956a0a04d7423972e81"


def main() -> int:
    raw = subprocess.check_output(
        ["git", "show", f"{GOOD_SHA}:app/engine_tick.py"],
        cwd=ROOT,
    ).decode("utf-8")

    # Expectancy gate
    if "session_expectancy_neg" not in raw:
        gate = (
            "    exp_block = None\n"
            "    try:\n"
            "        exp = state.session_expectancy() if hasattr(state, \"session_expectancy\") else {}\n"
            "        n = int(exp.get(\"n\") or 0)\n"
            "        e = exp.get(\"expectancy_usdt\")\n"
            "        min_n = int(__import__(\"os\").getenv(\"EXPECTANCY_MIN_TRADES\", \"12\") or 12)\n"
            "        if n >= min_n and e is not None and float(e) < 0:\n"
            "            exp_block = f\"session_expectancy_neg:{float(e):.4f}_n={n}\"\n"
            "            if ticks % 120 == 0:\n"
            "                log.warning(\"expectancy gate: %s — tightening until fee-net > 0\", exp_block)\n"
            "    except Exception:\n"
            "        exp_block = None\n\n"
        )
        raw = raw.replace("    can_enter = (", gate + "    can_enter = (", 1)

    if "and exp_block is None" not in raw:
        raw = raw.replace(
            "and churn_block is None\n        and cb_allow",
            "and churn_block is None\n        and exp_block is None\n        and cb_allow",
            1,
        )

    if "if exp_block:" not in raw:
        raw = raw.replace(
            "        if churn_block:\n            bl = [str(churn_block)] + bl\n        if not cb_allow:",
            "        if churn_block:\n            bl = [str(churn_block)] + bl\n"
            "        if exp_block:\n            bl = [str(exp_block)] + bl\n        if not cb_allow:",
            1,
        )

    # Single source of truth for hourly anti-churn
    raw, n = re.subn(
        r"\n[ \t]*try:\n[ \t]*state\.hourly_trade_ts = list\(getattr\(state, \"hourly_trade_ts\", \[\]\) or \[\]\) \+ \[time\.time\(\)\]\n[ \t]*except Exception:\n[ \t]*pass\n",
        "\n",
        raw,
    )
    print(f"removed_manual_hourly_appends={n}")

    TARGET.write_text(raw, encoding="utf-8")
    print(f"wrote {TARGET} bytes={len(raw)}")
    if "async def handle_tick" not in raw or "and exp_block is None" not in raw:
        print("ERROR: restore incomplete", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
