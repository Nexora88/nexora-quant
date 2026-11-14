"""Per-depth-tick trading core — body shipped as base64 parts under app/_et_b64/.

On first import, parts are decoded into this module's namespace (handle_tick).
This avoids a single mega-blob in git history while keeping one import path.
"""
from __future__ import annotations

import base64
from pathlib import Path

_PARTS = Path(__file__).resolve().parent / "_et_b64"


def _load_source() -> str:
    parts = sorted(_PARTS.glob("part_*.b64"))
    if not parts:
        raise RuntimeError(
            "Missing app/_et_b64/part_*.b64 — restore engine_tick body parts."
        )
    b64 = "".join(p.read_text(encoding="ascii").strip() for p in parts)
    text = base64.b64decode(b64.encode("ascii")).decode("utf-8")
    if "async def handle_tick" not in text:
        raise RuntimeError("Decoded engine_tick body is invalid")
    return text


_ns: dict = {"__name__": "app.engine_tick", "__file__": str(Path(__file__).resolve())}
exec(compile(_load_source(), str(Path(__file__).resolve()), "exec"), _ns)
handle_tick = _ns["handle_tick"]
__all__ = ["handle_tick"]
