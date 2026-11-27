"""Synthetic data exclusively for offline approval validation tests."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from app.build_info import source_fingerprint
from app.live_approval import APPROVAL_ARTIFACTS, APPROVAL_VERSION, digest_json
from app.live_execution_evidence import SpotEvidenceScope

ROOT = Path(__file__).resolve().parents[1]


def write_approval_stamp(stamp, profile):
    artifacts = {}
    for label in APPROVAL_ARTIFACTS:
        path = stamp.parent / f"fixture-{label}"
        path.write_text(f"synthetic {label}", encoding="utf-8")
        artifacts[label] = {"path": str(path.resolve()), "sha256": sha256(path.read_bytes()).hexdigest()}
    stamp.write_text(json.dumps({
        "version": APPROVAL_VERSION, "ok": True, "ts": datetime.now(timezone.utc).isoformat(),
        "source_fingerprint": source_fingerprint(ROOT), "profile_sha256": digest_json(profile),
        "account_binding": SpotEvidenceScope(77, False, profile["symbol"].upper()).stamp()["account_binding"],
        "artifacts": artifacts,
    }), encoding="utf-8")
