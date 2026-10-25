"""Durable empirical execution-cost calibration.

This is an execution-cost estimate, not a price forecast or profitability signal.
Corrupt/mismatched persisted state is ignored so callers remain uncalibrated and fail closed.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
import json
import logging
import math
import os
from pathlib import Path
import tempfile

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExecutionSample:
    latency_ms: float
    cost_bps: float


@dataclass(slots=True)
class _PendingFill:
    side: str
    decision_mid: float
    fill_price: float
    latency_ms: float
    filled_at_ms: int


class ObservedExecutionCostModel:
    """Rolling empirical p75 cost estimate; costs are basis points."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        *,
        min_samples: int = 30,
        horizon_ms: int = 1000,
        window_size: int = 500,
        persistence_path: str | Path | None = None,
    ) -> None:
        if min_samples < 2 or horizon_ms < 1 or window_size < min_samples:
            raise ValueError("invalid calibration window")
        self.min_samples = min_samples
        self.horizon_ms = horizon_ms
        self.window_size = window_size
        self.persistence_path = Path(persistence_path) if persistence_path else None
        self.samples: deque[ExecutionSample] = deque(maxlen=window_size)
        self.pending: deque[_PendingFill] = deque(maxlen=window_size)
        self.latest_mid: float | None = None
        self.latest_mid_at_ms: int | None = None
        if self.persistence_path:
            self._load()

    @staticmethod
    def _finite_nonnegative(value: object) -> bool:
        return isinstance(value, (int, float)) and math.isfinite(value) and value >= 0

    def _load(self) -> None:
        path = self.persistence_path
        assert path is not None
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if (
                data.get("schema_version") != self.SCHEMA_VERSION
                or data.get("min_samples") != self.min_samples
                or data.get("horizon_ms") != self.horizon_ms
                or data.get("window_size") != self.window_size
            ):
                raise ValueError("calibration schema/configuration mismatch")
            samples = data["samples"]
            pending = data["pending"]
            if not isinstance(samples, list) or not isinstance(pending, list):
                raise ValueError("calibration arrays are invalid")
            if len(samples) > self.window_size or len(pending) > self.window_size:
                raise ValueError("calibration window exceeds configured maximum")
            parsed_samples = []
            for item in samples:
                latency, cost = item["latency_ms"], item["cost_bps"]
                if not self._finite_nonnegative(latency) or not self._finite_nonnegative(cost):
                    raise ValueError("invalid persisted execution sample")
                parsed_samples.append(ExecutionSample(float(latency), float(cost)))
            parsed_pending = []
            for item in pending:
                if item["side"] not in ("buy", "sell"):
                    raise ValueError("invalid persisted fill side")
                values = [item["decision_mid"], item["fill_price"], item["latency_ms"], item["filled_at_ms"]]
                if not all(self._finite_nonnegative(v) for v in values) or min(values[:2]) <= 0:
                    raise ValueError("invalid persisted pending fill")
                parsed_pending.append(_PendingFill(
                    item["side"], float(item["decision_mid"]), float(item["fill_price"]),
                    float(item["latency_ms"]), int(item["filled_at_ms"]),
                ))
            self.samples.extend(parsed_samples)
            self.pending.extend(parsed_pending)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self.samples.clear()
            self.pending.clear()
            log.warning("Ignoring invalid execution-cost calibration; entries remain gated: %s", exc)

    def _save(self) -> None:
        path = self.persistence_path
        if path is None:
            return
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "min_samples": self.min_samples,
            "horizon_ms": self.horizon_ms,
            "window_size": self.window_size,
            "samples": [asdict(sample) for sample in self.samples],
            "pending": [asdict(item) for item in self.pending],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=f".{path.name}.", suffix=".tmp", delete=False,
            ) as tmp:
                tmp_name = tmp.name
                json.dump(payload, tmp, separators=(",", ":"), allow_nan=False)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, path)
        except OSError:
            log.exception("Could not persist execution-cost calibration; live entry remains gated")
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
            # Do not throw from market-data processing; the state is not claimed durable.

    def record_fill(
        self, *, side: str, decision_mid: float, fill_price: float,
        latency_ms: float, filled_at_ms: int,
    ) -> None:
        side = side.lower()
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        values = (decision_mid, fill_price, latency_ms, filled_at_ms)
        if not all(self._finite_nonnegative(v) for v in values) or decision_mid <= 0 or fill_price <= 0:
            raise ValueError("prices must be positive and latency/timestamp non-negative")
        self.pending.append(_PendingFill(side, float(decision_mid), float(fill_price),
                                         float(latency_ms), int(filled_at_ms)))
        self._save()

    def observe_mid(self, mid: float, timestamp_ms: int) -> None:
        if not math.isfinite(mid) or mid <= 0:
            return
        self.latest_mid, self.latest_mid_at_ms = mid, timestamp_ms
        keep: deque[_PendingFill] = deque(maxlen=self.pending.maxlen)
        changed = False
        while self.pending:
            item = self.pending.popleft()
            if timestamp_ms - item.filled_at_ms < self.horizon_ms:
                keep.append(item)
                continue
            if item.side == "buy":
                shortfall = max(0.0, (item.fill_price - item.decision_mid) / item.decision_mid)
                adverse = max(0.0, (item.fill_price - mid) / item.fill_price)
            else:
                shortfall = max(0.0, (item.decision_mid - item.fill_price) / item.decision_mid)
                adverse = max(0.0, (mid - item.fill_price) / item.fill_price)
            self.samples.append(ExecutionSample(item.latency_ms, (shortfall + adverse) * 10_000))
            changed = True
        self.pending = keep
        if changed:
            self._save()

    def estimate_cost_bps(self, *, latency_ms: float | None = None) -> float | None:
        """Return empirical p75 adverse cost, or None until calibrated."""
        if len(self.samples) < self.min_samples:
            return None
        eligible = list(self.samples)
        if latency_ms is not None:
            slower = [sample for sample in eligible if sample.latency_ms >= latency_ms]
            eligible = slower if len(slower) >= self.min_samples else eligible
        costs = sorted(sample.cost_bps for sample in eligible)
        if len(costs) < self.min_samples:
            return None
        index = min(len(costs) - 1, int(0.75 * (len(costs) - 1) + 0.999999))
        return costs[index]

    def estimate_latency_ms(self) -> float | None:
        if len(self.samples) < self.min_samples:
            return None
        latencies = sorted(sample.latency_ms for sample in self.samples)
        index = min(len(latencies) - 1, int(0.75 * (len(latencies) - 1) + 0.999999))
        return latencies[index]

    @property
    def sample_count(self) -> int:
        return len(self.samples)
