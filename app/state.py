"""Runtime state — body as zlib b64 in app/_state_body.z.b64."""
from __future__ import annotations
import base64
import zlib
from pathlib import Path

_p = Path(__file__).with_name("_state_body.z.b64")
if _p.is_file() and _p.stat().st_size > 100:
    _src = zlib.decompress(base64.b64decode(_p.read_text().strip().encode())).decode()
    _ns = {"__name__": "app.state", "__file__": __file__}
    exec(compile(_src, __file__, "exec"), _ns)
    RuntimeState = _ns["RuntimeState"]
    __all__ = ["RuntimeState"]
else:
    raise RuntimeError("Missing app/_state_body.z.b64 — restore state module body")
