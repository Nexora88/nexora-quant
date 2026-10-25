"""Lightweight market-regime classifier from spread, volatility, and volume proxies.

Not a full GMM; uses rolling thresholds suitable for online L2 streams without
heavyweight ML dependencies. Regime switches which signal family is trusted.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from math import sqrt


class MarketRegime(str, Enum):
    TREND = "trend"
    RANGE = "range"
    STRESSED = "stressed"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class RegimeSnapshot:
    regime: MarketRegime
    volatility_bps: float
    avg_spread_bps: float
    volume_proxy: float
    confidence: float


class RegimeClassifier:
    def __init__(
        self,
        *,
        window: int = 120,
        high_vol_bps: float = 25.0,
        wide_spread_bps: float = 12.0,
    ) -> None:
        self._mids: deque[float] = deque(maxlen=window)
        self._spreads: deque[float] = deque(maxlen=window)
        self._volumes: deque[float] = deque(maxlen=window)
        self.high_vol_bps = high_vol_bps
        self.wide_spread_bps = wide_spread_bps

    def update(self, *, mid: float, spread_bps: float, volume_proxy: float) -> RegimeSnapshot:
        if mid > 0:
            self._mids.append(mid)
        if spread_bps >= 0:
            self._spreads.append(spread_bps)
        if volume_proxy >= 0:
            self._volumes.append(volume_proxy)
        return self.classify()

    def _vol_bps(self) -> float:
        if len(self._mids) < 10:
            return 0.0
        rets = []
        mids = list(self._mids)
        for i in range(1, len(mids)):
            if mids[i - 1] > 0:
                rets.append((mids[i] / mids[i - 1] - 1.0) * 10_000.0)
        if len(rets) < 5:
            return 0.0
        mu = sum(rets) / len(rets)
        var = sum((r - mu) ** 2 for r in rets) / max(1, len(rets) - 1)
        return sqrt(var)

    def classify(self) -> RegimeSnapshot:
        vol = self._vol_bps()
        avg_spread = sum(self._spreads) / len(self._spreads) if self._spreads else 0.0
        vol_proxy = sum(self._volumes) / len(self._volumes) if self._volumes else 0.0
        if len(self._mids) < 15:
            return RegimeSnapshot(MarketRegime.UNKNOWN, vol, avg_spread, vol_proxy, 0.2)
        if avg_spread >= self.wide_spread_bps or vol >= self.high_vol_bps * 1.5:
            regime = MarketRegime.STRESSED
            conf = 0.7
        elif vol >= self.high_vol_bps:
            regime = MarketRegime.TREND
            conf = 0.65
        else:
            regime = MarketRegime.RANGE
            conf = 0.6
        return RegimeSnapshot(regime, vol, avg_spread, vol_proxy, conf)
