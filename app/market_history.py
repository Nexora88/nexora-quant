"""Append-only compressed market-event recording and deterministic replay.

Records are research fixtures, not exchange-authoritative history.
When enabled=False, append is a no-op (paper default).
"""
from __future__ import annotations

import gzip
from hashlib import file_digest
import json
import logging
from collections import deque
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger(__name__)


class MarketHistoryWriter:
    def __init__(
        self,
        path: str | Path,
        *,
        max_pending: int = 0,
        enabled: bool = True,
    ) -> None:
        self.enabled = bool(enabled)
        self.path = Path(path)
        self._compressed = self.path.suffix.lower() == ".gz"
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._last_timestamp_ns = -1
        self._max_pending = max(0, int(max_pending))
        self._pending: deque[str] = deque()
        self._dropped = 0
        self._written = 0
        self._write_error: OSError | None = None

    def _check_writer(self) -> None:
        if self._write_error is not None:
            raise RuntimeError("Market capture is incomplete; start a new output file") from self._write_error

    def stats(self) -> dict[str, int]:
        return {
            "pending": len(self._pending),
            "max_pending": self._max_pending,
            "dropped": self._dropped,
            "written": self._written,
            "enabled": int(self.enabled),
        }

    def append(self, *, timestamp_ns: int, event_type: str, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        self._check_writer()
        if isinstance(timestamp_ns, bool) or not isinstance(timestamp_ns, int) or timestamp_ns < 0:
            raise ValueError("timestamp_ns must be a non-negative integer")
        if timestamp_ns < self._last_timestamp_ns:
            raise ValueError("events must be appended in nondecreasing timestamp order")
        if not event_type or not isinstance(event_type, str):
            raise ValueError("event_type is required")
        record = {
            "timestamp_ns": timestamp_ns,
            "event_type": event_type,
            "payload": payload,
        }
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self._last_timestamp_ns = timestamp_ns
        if self._max_pending <= 0:
            self._write_line(encoded)
            return
        # Flush a full batch instead of evicting the oldest events. The old
        # bounded-deque behavior silently discarded market history whenever
        # the engine produced events faster than shutdown-time flushing.
        self._pending.append(encoded)
        if len(self._pending) >= self._max_pending:
            self.flush()

    def _write_line(self, encoded: str) -> None:
        open_fn = gzip.open if self._compressed else open
        try:
            with open_fn(self.path, "at", encoding="utf-8") as stream:
                stream.write(encoded + "\n")
        except OSError as exc:
            self._write_error = exc
            raise
        self._written += 1

    def flush(self) -> None:
        if not self.enabled:
            return
        self._check_writer()
        if not self._pending:
            return
        batch = list(self._pending)
        open_fn = gzip.open if self._compressed else open
        try:
            with open_fn(self.path, "at", encoding="utf-8") as stream:
                for encoded in batch:
                    stream.write(encoded + "\n")
        except OSError as exc:
            # A failed flush may already have appended bytes. Never retry the
            # batch into the same file and accidentally duplicate some rows.
            self._write_error = exc
            raise
        self._pending.clear()
        self._written += len(batch)

    def close(self) -> None:
        self.flush()


def replay_market_history(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield validated plain or gzip JSONL records in file order; fail closed on malformed rows."""
    last_timestamp_ns = -1
    source = Path(path)
    open_fn = gzip.open if source.suffix.lower() == ".gz" else open
    with open_fn(source, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as err:
                raise ValueError("invalid JSON at line %s" % line_number) from err
            if not isinstance(record, dict):
                raise ValueError("record at line %s must be an object" % line_number)
            timestamp = record.get("timestamp_ns")
            if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
                raise ValueError("invalid timestamp at line %s" % line_number)
            if timestamp < last_timestamp_ns:
                raise ValueError("out-of-order timestamp at line %s" % line_number)
            if not isinstance(record.get("event_type"), str) or not record["event_type"]:
                raise ValueError("invalid event_type at line %s" % line_number)
            if not isinstance(record.get("payload"), dict):
                raise ValueError("invalid payload at line %s" % line_number)
            last_timestamp_ns = timestamp
            yield record


def verify_capture_archive(path: str | Path, manifest_path: str | Path) -> str:
    """Require a complete bounded capture and return its verified archive hash."""
    archive = Path(path).resolve()
    manifest = Path(manifest_path).resolve()
    if archive.parent != manifest.parent:
        raise ValueError("Archive and capture manifest must be in the same directory")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1 or payload.get("source") != "binance_spot_public"
        or payload.get("research_only") is not True or payload.get("coverage_ok") is not True
        or not isinstance(payload.get("captures"), list)
    ):
        raise ValueError("Capture manifest did not pass coverage checks")
    matches = [item for item in payload["captures"] if isinstance(item, dict) and item.get("file") == archive.name]
    if len(matches) != 1 or matches[0].get("coverage_ok") is not True:
        raise ValueError("Archive has no passing capture in this manifest")
    with archive.open("rb") as stream:
        digest = file_digest(stream, "sha256").hexdigest()
    if matches[0].get("sha256") != digest:
        raise ValueError("Capture archive hash does not match its manifest")
    return digest
