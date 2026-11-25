"""Chronological research splits without shared timestamps across a boundary."""
from bisect import bisect_left
from math import isfinite
import json
from typing import Iterable

DEFAULT_EMBARGO_SECONDS = 60.0


def event_timestamps(rows: Iterable[str]) -> list[int]:
    values: list[int] = []
    for index, row in enumerate(rows, 1):
        record = json.loads(row)
        ts = record.get("timestamp_ns") if isinstance(record, dict) else None
        if type(ts) is not int or ts < 0 or (values and ts < values[-1]):
            raise ValueError(f"invalid/out-of-order timestamp at event {index}")
        values.append(ts)
    return values


def embargo_nanoseconds(seconds: float) -> int:
    ns = seconds * 1_000_000_000
    if not isfinite(ns) or ns < 0:
        raise ValueError("embargo seconds must be finite and nonnegative")
    return round(ns)


def purged_bounds(
    timestamps: list[int], proposed_start: int, proposed_end: int, embargo_ns: int,
) -> tuple[int, int, int]:
    """Snap test boundaries to full timestamp groups, then purge training tail."""
    test_start_ns = timestamps[proposed_start]
    start = bisect_left(timestamps, test_start_ns)
    end = (
        bisect_left(timestamps, timestamps[proposed_end])
        if proposed_end < len(timestamps) else len(timestamps)
    )
    train_end = bisect_left(timestamps, test_start_ns - embargo_ns)
    if train_end < 100 or end - start < 50:
        raise ValueError("train/test split too small after time embargo and timestamp grouping")
    return train_end, start, end
