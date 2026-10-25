"""Empirical execution-cost calibration from observed fills and post-fill mids.

This deliberately refuses to estimate from too few samples. It is not a price
forecast: it estimates adverse execution cost conditional on observed latency.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from statistics import quantiles


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
    """Rolling empirical p75 cost estimate; costs are basis points.

    A sample combines execution shortfall against the decision mid with
    post-fill adverse movement measured after a configurable horizon.
    The model returns None until min_samples mature; callers should fail closed.
    """

    def __init__(
        self,
        *,
        min_samples: int = 30,
        horizon_ms: int = 1000,
        window_size: int = 500,
    ) -> None:
        if min_samples < 2 or horizon_ms < 1 or window_size < min_samples:
            raise ValueError("invalid calibration window")
        self.min_samples = min_samples
        self.horizon_ms = horizon_ms
        self.samples: deque[ExecutionSample] = deque(maxlen=window_size)
        self.pending: deque[_PendingFill] = deque(maxlen=window_size)
        self.latest_mid: float | None = None
        self.latest_mid_at_ms: int | None = None

    def record_fill(
        self,
        *,
        side: str,
        decision_mid: float,
        fill_price: float,
        latency_ms: float,
        filled_at_ms: int,
    ) -> None:
        side = side.lower()
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        if decision_mid <= 0 or fill_price <= 0 or latency_ms < 0:
            raise ValueError("prices must be positive and latency non-negative")
        self.pending.append(_PendingFill(side, decision_mid, fill_price, latency_ms, filled_at_ms))

    def observe_mid(self, mid: float, timestamp_ms: int) -> None:
        if mid <= 0:
            return
        self.latest_mid, self.latest_mid_at_ms = mid, timestamp_ms
        keep: deque[_PendingFill] = deque(maxlen=self.pending.maxlen)
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
            self.samples.append(
                ExecutionSample(item.latency_ms, (shortfall + adverse) * 10_000)
            )
        self.pending = keep

    def estimate_cost_bps(self, *, latency_ms: float | None = None) -> float | None:
        """Return empirical 75th-percentile adverse cost, or None until calibrated."""
        if len(self.samples) < self.min_samples:
            return None
        eligible = list(self.samples)
        if latency_ms is not None:
            slower = [sample for sample in eligible if sample.latency_ms >= latency_ms]
            # Avoid pretending a thin latency bucket is calibrated; use all data
            # only if the slower-latency bucket has enough observations.
            eligible = slower if len(slower) >= self.min_samples else eligible
        costs = sorted(sample.cost_bps for sample in eligible)
        if len(costs) < self.min_samples:
            return None
        index = min(len(costs) - 1, int(0.75 * (len(costs) - 1) + 0.999999))
        return costs[index]

    @property
    def sample_count(self) -> int:
        return len(self.samples)
