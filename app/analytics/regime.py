"""Lightweight market-regime classifier from spread, volatility, and wick proxies.

Not a full GMM; uses rolling thresholds suitable for online L2 streams without
heavyweight ML dependencies. Regime switches which signal family is trusted and
can request a hard pause (no new entries) in choppy / liquidation-wick conditions.
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
    CHOPPY = "choppy"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class RegimeSnapshot:
    regime: MarketRegime
    volatility_bps: float
    avg_spread_bps: float
    volume_proxy: float
    confidence: float
    pause_entries: bool = False
    wick_score: float = 0.0
    chop_score: float = 0.0
    detail: str = ""


class RegimeClassifier:
    def __init__(
        self,
        *,
        window: int = 120,
        high_vol_bps: float = 25.0,
        wide_spread_bps: float = 12.0,
        # Absolute mid jump (bps) treated as a candidate liquidation wick.
        wick_jump_bps: float = 35.0,
        # How many bars after a wick we keep pause_entries.
        wick_cooldown: int = 8,
        # Sign-flip rate above this → choppy (tester) market.
        chop_flip_ratio: float = 0.55,
    ) -> None:
        self._mids: deque[float] = deque(maxlen=window)
        self._spreads: deque[float] = deque(maxlen=window)
        self._volumes: deque[float] = deque(maxlen=window)
        self._signed_rets: deque[float] = deque(maxlen=window)
        self.high_vol_bps = high_vol_bps
        self.wide_spread_bps = wide_spread_bps
        self.wick_jump_bps = wick_jump_bps
        self.wick_cooldown = max(1, wick_cooldown)
        self.chop_flip_ratio = chop_flip_ratio
        self._wick_cooldown_left = 0
        self._last_wick_bps = 0.0

    def update(self, *, mid: float, spread_bps: float, volume_proxy: float) -> RegimeSnapshot:
        if mid > 0:
            if self._mids:
                prev = self._mids[-1]
                if prev > 0:
                    ret_bps = (mid / prev - 1.0) * 10_000.0
                    self._signed_rets.append(ret_bps)
                    if abs(ret_bps) >= self.wick_jump_bps:
                        self._wick_cooldown_left = self.wick_cooldown
                        self._last_wick_bps = abs(ret_bps)
            self._mids.append(mid)
        if spread_bps >= 0:
            self._spreads.append(spread_bps)
        if volume_proxy >= 0:
            self._volumes.append(volume_proxy)
        if self._wick_cooldown_left > 0:
            self._wick_cooldown_left -= 1
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

    def _chop_score(self) -> float:
        """Fraction of consecutive return sign flips in recent window (0–1)."""
        rets = list(self._signed_rets)
        if len(rets) < 12:
            return 0.0
        flips = 0
        pairs = 0
        for i in range(1, len(rets)):
            a, b = rets[i - 1], rets[i]
            if a == 0 or b == 0:
                continue
            pairs += 1
            if (a > 0) != (b > 0):
                flips += 1
        if pairs < 8:
            return 0.0
        return flips / pairs

    def classify(self) -> RegimeSnapshot:
        vol = self._vol_bps()
        avg_spread = sum(self._spreads) / len(self._spreads) if self._spreads else 0.0
        vol_proxy = sum(self._volumes) / len(self._volumes) if self._volumes else 0.0
        chop = self._chop_score()
        wick_active = self._wick_cooldown_left > 0
        wick_score = self._last_wick_bps if wick_active else 0.0

        if len(self._mids) < 15:
            return RegimeSnapshot(
                MarketRegime.UNKNOWN, vol, avg_spread, vol_proxy, 0.2,
                pause_entries=False, wick_score=0.0, chop_score=chop, detail="warming",
            )

        # Hard stress: wide spread or extreme vol, or active liquidation wick.
        if avg_spread >= self.wide_spread_bps or vol >= self.high_vol_bps * 1.5 or wick_active:
            regime = MarketRegime.STRESSED
            conf = 0.75 if wick_active else 0.7
            pause = True
            detail = (
                f"wick_{wick_score:.0f}bps_cd={self._wick_cooldown_left}"
                if wick_active
                else f"vol={vol:.1f}/spread={avg_spread:.1f}"
            )
        elif chop >= self.chop_flip_ratio and vol < self.high_vol_bps:
            # Testere (choppy) — high flip rate without sustained trend vol.
            regime = MarketRegime.CHOPPY
            conf = 0.65
            pause = True
            detail = f"chop={chop:.2f}"
        elif vol >= self.high_vol_bps:
            regime = MarketRegime.TREND
            conf = 0.65
            pause = False
            detail = f"trend_vol={vol:.1f}"
        else:
            regime = MarketRegime.RANGE
            conf = 0.6
            pause = False
            detail = f"range_vol={vol:.1f}"

        return RegimeSnapshot(
            regime=regime,
            volatility_bps=vol,
            avg_spread_bps=avg_spread,
            volume_proxy=vol_proxy,
            confidence=conf,
            pause_entries=pause,
            wick_score=wick_score,
            chop_score=chop,
            detail=detail,
        )
