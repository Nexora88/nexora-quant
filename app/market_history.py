"""Append-only compressed market-event recording and deterministic replay.

Under multi-symbol L2 bursts, ``max_pending`` bounds RAM. When ``enabled=False``,
append is a no-op (paper default) so the process is not flooded with backpressure logs.
"""
from __future__ import annotations

import gzip
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
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._last_timestamp_ns = -1
        self._max_pending = max(0, int(max_pending))
        self._pending: deque[str] = deque()
        self._dropped = 0
        self._written = 0

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
        while len(self._pending) >= self._max_pending:
            self._pending.popleft()
            self._dropped += 1
            if self._dropped == 1 or self._dropped % 500 == 0:
                log.warning(
                    "MarketHistoryWriter backpressure path=%s dropped=%s pending=%s",
                    self.path,
                    self._dropped,
                    len(self._pending),
                )
        self._pending.append(encoded)

    def _write_line(self, encoded: str) -> None:
        with gzip.open(self.path, "at", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
        self._written += 1

    def flush(self) -> None:
        if not self.enabled:
            return
        while self._pending:
            self._write_line(self._pending.popleft())

    def close(self) -> None:
        self.flush()

    def __enter__(self) -> "MarketHistoryWriter":
        return self

    def __exit__(self, *args) -> None:
        self.close()
