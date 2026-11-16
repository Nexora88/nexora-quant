"""Build fingerprint used to invalidate stale mainnet approval stamps."""
from __future__ import annotations

import hashlib
from pathlib import Path


def source_fingerprint(root: str | Path) -> str:
    """Hash runtime Python sources and compressed engine payloads deterministically."""
    base = Path(root).resolve()
    digest = hashlib.sha256()
    app_dir = base / "app"
    script_dir = base / "scripts"
    paths: list[Path] = []
    if app_dir.is_dir():
        paths.extend(
            path for path in app_dir.rglob("*")
            if path.is_file()
            and (
                path.suffix == ".py"
                or (path.parent.name == "_et_b64" and path.name.startswith("body.z"))
            )
            and "__pycache__" not in path.parts
        )
    if script_dir.is_dir():
        paths.extend(
            path for path in script_dir.rglob("*.py")
            if path.is_file() and "__pycache__" not in path.parts
        )
    for path in sorted(set(paths)):
        relative = path.relative_to(base).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()
