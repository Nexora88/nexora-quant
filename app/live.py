"""LiveExecutor restored from base64 chunks."""
from __future__ import annotations
from pathlib import Path
import base64
_root = Path(__file__).resolve().parent
_b64 = "".join((_root / f"_live_b64_{i}.txt").read_text() for i in range(5))
_src = base64.b64decode(_b64).decode()
_ns: dict = {"__name__": "app.live"}
exec(compile(_src, "app/live.py", "exec"), _ns)
LiveExecutor = _ns["LiveExecutor"]
__all__ = ["LiveExecutor"]
