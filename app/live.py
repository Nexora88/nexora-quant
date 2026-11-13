"""Live executor — reconstructed from parts to avoid tool size limits."""
from __future__ import annotations

from app._live_part_a import PART_A
from app._live_part_b import PART_B
from app._live_part_c import PART_C

_src = PART_A + PART_B + PART_C
_ns: dict = {"__name__": "app.live"}
exec(compile(_src, "app/live.py", "exec"), _ns)
globals().update({k: v for k, v in _ns.items() if not k.startswith("_")})
LiveExecutor = _ns["LiveExecutor"]
__all__ = ["LiveExecutor"]
