"""Per-depth-tick trading core.

Body is shipped as zlib+base64 halves under app/_et_b64/body.z0 + body.z1
to keep git commits reliable. Decodes into handle_tick on import.
"""
from __future__ import annotations

import base64
import zlib
from pathlib import Path

_DIR = Path(__file__).resolve().parent / "_et_b64"


def _load_source() -> str:
    z0 = _DIR / "body.z0"
    z1 = _DIR / "body.z1"
    if not z0.is_file() or not z1.is_file():
        raise RuntimeError("Missing app/_et_b64/body.z0 or body.z1")
    b64 = z0.read_text(encoding="ascii").strip() + z1.read_text(encoding="ascii").strip()
    text = zlib.decompress(base64.b64decode(b64.encode("ascii"))).decode("utf-8")
    if "async def handle_tick" not in text:
        raise RuntimeError("Decoded engine_tick body invalid")
    return text


_ns: dict = {"__name__": "app.engine_tick", "__file__": str(Path(__file__).resolve())}
exec(compile(_load_source(), str(Path(__file__).resolve()), "exec"), _ns)
handle_tick = _ns["handle_tick"]
__all__ = ["handle_tick"]
