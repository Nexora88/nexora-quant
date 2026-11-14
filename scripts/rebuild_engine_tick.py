#!/usr/bin/env python3
"""One-shot: rebuild app/engine_tick.py from b64 part files shipped in repo."""
from __future__ import annotations
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARTS_DIR = ROOT / "app" / "_et_b64"
TARGET = ROOT / "app" / "engine_tick.py"

def main() -> None:
    parts = sorted(PARTS_DIR.glob("part_*.b64"))
    if not parts:
        raise SystemExit(f"no parts in {PARTS_DIR}")
    b64 = "".join(p.read_text(encoding="ascii").strip() for p in parts)
    text = base64.b64decode(b64.encode("ascii")).decode("utf-8")
    if "async def handle_tick" not in text:
        raise SystemExit("decoded body missing handle_tick")
    TARGET.write_text(text, encoding="utf-8")
    print(f"restored {TARGET} ({len(text)} bytes) from {len(parts)} parts")

if __name__ == "__main__":
    main()
