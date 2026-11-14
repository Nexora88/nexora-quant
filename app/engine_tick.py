"""Per-depth-tick entrypoint — loads body from shipped app/_engine_tick_body.py."""
from __future__ import annotations

from pathlib import Path

_CACHE = Path(__file__).resolve().with_name("_engine_tick_body.py")


def _load():
    if not _CACHE.is_file() or _CACHE.stat().st_size < 5_000:
        raise RuntimeError(
            "app/_engine_tick_body.py missing or truncated. "
            "Restore full handle_tick body to app/_engine_tick_body.py"
        )
    text = _CACHE.read_text(encoding="utf-8")
    if "async def handle_tick" not in text:
        raise RuntimeError("app/_engine_tick_body.py does not define handle_tick")
    ns: dict = {"__name__": "app.engine_tick"}
    exec(compile(text, str(_CACHE), "exec"), ns)
    return ns


_ns = _load()
handle_tick = _ns["handle_tick"]
__all__ = ["handle_tick"]
