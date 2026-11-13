"""Live / testnet executor (source assembled from _live_src_* parts)."""
from __future__ import annotations

from app._live_src_0 import SRC as _S0
from app._live_src_1 import SRC as _S1
from app._live_src_2 import SRC as _S2

_src = _S0 + _S1 + _S2
_ns: dict = {"__name__": "app.live"}
exec(compile(_src, "app/live.py", "exec"), _ns)
LiveExecutor = _ns["LiveExecutor"]
__all__ = ["LiveExecutor"]
