"""Local approval bindings. These are integrity checks, not remote attestations."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
import json
import re

from app.build_info import source_fingerprint

APPROVAL_VERSION = 2
APPROVAL_ARTIFACTS = {"overnight", "scorecard", "oos", "testnet"}


def digest_json(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def is_digest(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def read_mainnet_approval(stamp: Path, *, root: Path, profile: dict) -> str:
    """Verify the immutable bindings at startup and return the approved account binding."""
    if not stamp.is_file():
        raise ValueError("Mainnet live blocked: run scripts/go_live_gate.py (missing GO_LIVE stamp)")
    try:
        approval = json.loads(stamp.read_text(encoding="utf-8"))
        if not isinstance(approval, dict) or approval.get("version") != APPROVAL_VERSION or approval.get("ok") is not True:
            raise ValueError("legacy, incomplete, or unapproved stamp")
        approved_at = datetime.fromisoformat(approval["ts"])
        if approved_at.utcoffset() is None:
            raise ValueError("missing timezone")
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise ValueError("Mainnet live blocked: GO_LIVE stamp is invalid") from exc
    age = (datetime.now(timezone.utc) - approved_at).total_seconds()
    if age < -300 or age > 7 * 24 * 3600:
        raise ValueError("Mainnet live blocked: GO_LIVE stamp is expired or from the future")
    if approval.get("source_fingerprint") != source_fingerprint(root):
        raise ValueError("Mainnet live blocked: source changed since approval")
    if approval.get("profile_sha256") != digest_json(profile):
        raise ValueError("Mainnet live blocked: live settings changed since approval")
    binding = approval.get("account_binding")
    if not is_digest(binding):
        raise ValueError("Mainnet live blocked: approval has no account binding")

    artifacts = approval.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != APPROVAL_ARTIFACTS:
        raise ValueError("Mainnet live blocked: approval has no complete artifact bindings")
    for label, artifact in artifacts.items():
        if not isinstance(artifact, dict) or not is_digest(artifact.get("sha256")):
            raise ValueError(f"Mainnet live blocked: invalid {label} artifact binding")
        try:
            path = Path(artifact["path"])
            if not path.is_absolute():
                raise ValueError("artifact path must be absolute")
            if sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                raise ValueError("hash mismatch")
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise ValueError(f"Mainnet live blocked: {label} artifact changed or unavailable") from exc
    return binding
