"""Live / testnet executor — loads body from shipped app/_live_body.py only.

No network fetch. Ship `_live_body.py` with the repo (canonical LiveExecutor).
"""
from __future__ import annotations

from pathlib import Path

_CACHE = Path(__file__).resolve().with_name("_live_body.py")


def _ensure_body() -> str:
    if not _CACHE.is_file() or _CACHE.stat().st_size < 10_000:
        raise RuntimeError(
            "app/_live_body.py missing or truncated. Restore from commit 8b0d7c62 "
            "or place full LiveExecutor source at app/_live_body.py."
        )
    text = _CACHE.read_text(encoding="utf-8")
    if "class LiveExecutor" not in text:
        raise RuntimeError("app/_live_body.py does not define LiveExecutor")
    return text


_src = _ensure_body()
_ns: dict = {"__name__": "app.live"}
exec(compile(_src, str(_CACHE), "exec"), _ns)
LiveExecutor = _ns["LiveExecutor"]
__all__ = ["LiveExecutor"]
