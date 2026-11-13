"""Live / testnet executor — loads canonical body from known-good commit blob.

The full LiveExecutor (OCO, reconcile, market orders) is too large for some
push paths; this module fetches the immutable blob once and caches it locally
as app/_live_body.py so subsequent imports are offline.
"""
from __future__ import annotations

from pathlib import Path
import urllib.request

_CANONICAL = (
    "https://raw.githubusercontent.com/Nexora88/nexora-quant/"
    "8b0d7c62350b43b6e07cb2a9a6052b3022c5f2c1/app/live.py"
)
_CACHE = Path(__file__).resolve().with_name("_live_body.py")


def _ensure_body() -> str:
    if _CACHE.is_file() and _CACHE.stat().st_size > 10_000:
        return _CACHE.read_text(encoding="utf-8")
    try:
        with urllib.request.urlopen(_CANONICAL, timeout=30) as resp:
            text = resp.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Could not load LiveExecutor body. Place full app/live.py content "
            "at app/_live_body.py or restore from commit 8b0d7c62."
        ) from exc
    if "class LiveExecutor" not in text or len(text) < 10_000:
        raise RuntimeError("Downloaded live body looks truncated")
    _CACHE.write_text(text, encoding="utf-8")
    return text


_src = _ensure_body()
_ns: dict = {"__name__": "app.live"}
exec(compile(_src, str(_CACHE), "exec"), _ns)
LiveExecutor = _ns["LiveExecutor"]
__all__ = ["LiveExecutor"]
