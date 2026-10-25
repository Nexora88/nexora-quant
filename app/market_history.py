"""Append-only compressed market-event recording and deterministic replay.

Records are research fixtures, not exchange-authoritative history. Timestamps are
UTC epoch nanoseconds supplied by the caller; use exchange event time when present
and preserve receive time separately in the payload for latency analysis.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Iterator


class MarketHistoryWriter:
    """Write gzip JSONL records without buffering an unbounded event queue."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._last_timestamp_ns = -1

    def append(self, *, timestamp_ns: int, event_type: str, payload: dict[str, Any]) -> None:
        if isinstance(timestamp_ns, bool) or timestamp_ns < 0:
            raise ValueError("timestamp_ns must be a non-negative integer")
        if not isinstance(timestamp_ns, int):
            raise ValueError("timestamp_ns must be an integer")
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
        with gzip.open(self.path, "at", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
        self._last_timestamp_ns = timestamp_ns


def replay_market_history(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield validated records in file order; malformed rows fail closed."""
    last_timestamp_ns = -1
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at line {line_number}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"record at line {line_number} must be an object")
            timestamp = record.get("timestamp_ns")
            if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
                raise ValueError(f"invalid timestamp at line {line_number}")
            if timestamp < last_timestamp_ns:
                raise ValueError(f"out-of-order timestamp at line {line_number}")
            if not isinstance(record.get("event_type"), str) or not record["event_type"]:
                raise ValueError(f"invalid event_type at line {line_number}")
            if not isinstance(record.get("payload"), dict):
                raise ValueError(f"invalid payload at line {line_number}")
            last_timestamp_ns = timestamp
            yield record
