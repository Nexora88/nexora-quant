"""Per-depth-tick entrypoint — loads body from part files or full body."""
from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).resolve().parent
_FULL = _DIR / "_engine_tick_body.py"
_P1 = _DIR / "_engine_tick_body_p1.py"
_P2 = _DIR / "_engine_tick_body_p2.py"


def _source() -> str:
    if _FULL.is_file() and _FULL.stat().st_size >= 5_000:
        text = _FULL.read_text(encoding="utf-8")
        if "async def handle_tick" in text:
            return text
    if _P1.is_file() and _P2.is_file():
        text = _P1.read_text(encoding="utf-8") + _P2.read_text(encoding="utf-8")
        if "async def handle_tick" in text:
            return text
    raise RuntimeError(
        "Missing engine_tick body. Need app/_engine_tick_body.py "
        "or app/_engine_tick_body_p1.py + _p2.py"
    )


_ns: dict = {"__name__": "app.engine_tick"}
exec(compile(_source(), str(_FULL if _FULL.is_file() else _P1), "exec"), _ns)
handle_tick = _ns["handle_tick"]
__all__ = ["handle_tick"]
