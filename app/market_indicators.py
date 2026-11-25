"""Closed-candle technical indicators; indicators are grouped, not counted as independent votes."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import isfinite
import json
import time
import urllib.parse
import urllib.request

from app.binance_rest import MAINNET_REST, TESTNET_REST


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    interval: str
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    closed: bool = True
    received_at: float | None = None


@dataclass(frozen=True, slots=True)
class IndicatorSnapshot:
    ready: bool
    close: float | None
    ema9: float | None
    ema21: float | None
    ema50: float | None
    ema200: float | None
    rsi14: float | None
    macd: float | None
    macd_signal: float | None
    macd_histogram: float | None
    vwap: float | None
    vwap_distance_bps: float | None
    atr14_pct: float | None
    volume_ratio: float | None
    volume_profile_poc: float | None
    trend_bias: str
    momentum_bias: str
    age_seconds: float | None
    note: str


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


class MarketIndicatorTracker:
    """Indicators are calculated only from closed Binance candles."""

    def __init__(self, *, max_1m: int = 1500, max_5m: int = 400) -> None:
        self._candles: dict[str, deque[Candle]] = {
            "1m": deque(maxlen=max_1m),
            "5m": deque(maxlen=max_5m),
        }

    def update(self, candle: Candle) -> IndicatorSnapshot:
        if not candle.closed or candle.interval not in self._candles:
            return self.snapshot()
        values = (candle.open, candle.high, candle.low, candle.close, candle.volume)
        if (
            not all(isfinite(float(v)) for v in values)
            or candle.open <= 0 or candle.low <= 0 or candle.high <= 0
            or candle.volume < 0 or candle.high < max(candle.open, candle.close)
            or candle.low > min(candle.open, candle.close)
        ):
            return self.snapshot()
        rows = self._candles[candle.interval]
        if rows and candle.open_time <= rows[-1].open_time:
            return self.snapshot()
        rows.append(candle)
        return self.snapshot()

    def seed(self, candles: list[Candle]) -> None:
        for candle in sorted(candles, key=lambda x: (x.interval, x.open_time)):
            self.update(candle)

    def closes(self, interval: str = "1m") -> list[float]:
        return [c.close for c in self._candles.get(interval, ())]

    def return_bps(self, *, interval: str = "1m", bars: int = 5) -> float | None:
        rows = list(self._candles.get(interval, ()))
        if bars < 1 or len(rows) <= bars:
            return None
        base = rows[-bars - 1].close
        return (rows[-1].close / base - 1.0) * 10_000.0 if base > 0 else None

    def correlation_with(
        self, other: "MarketIndicatorTracker", *, interval: str = "1m", periods: int = 30,
    ) -> float | None:
        if periods < 5:
            raise ValueError("periods must be >= 5")
        left = {c.open_time: c.close for c in self._candles.get(interval, ())}
        right = {c.open_time: c.close for c in other._candles.get(interval, ())}
        common = sorted(set(left) & set(right))
        if len(common) < periods + 1:
            return None
        common = common[-periods - 1:]
        x = [left[b] / left[a] - 1.0 for a, b in zip(common, common[1:]) if left[a] > 0]
        y = [right[b] / right[a] - 1.0 for a, b in zip(common, common[1:]) if right[a] > 0]
        if len(x) < periods or len(y) != len(x):
            return None
        mx, my = sum(x) / len(x), sum(y) / len(y)
        vx = sum((v - mx) ** 2 for v in x)
        vy = sum((v - my) ** 2 for v in y)
        if vx <= 1e-18 or vy <= 1e-18:
            return None
        cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
        return max(-1.0, min(1.0, cov / (vx * vy) ** 0.5))

    def snapshot(self, *, now: float | None = None) -> IndicatorSnapshot:
        current = time.time() if now is None else float(now)
        rows = list(self._candles["1m"])
        rows5 = list(self._candles["5m"])
        closes = [c.close for c in rows]
        close = closes[-1] if closes else None
        # Binance open_time marks the beginning of a candle, not its close.
        # Freshness must be measured from the end of the last CLOSED candle;
        # otherwise a perfectly current 1m candle appears ~60s old (and 5m
        # appears ~300s old), causing valid seeded history to fail readiness.
        age = (
            max(0.0, current - (rows[-1].open_time / 1000.0 + 60.0))
            if rows else None
        )

        e9, e21 = _ema(closes, 9), _ema(closes, 21)
        e50, e200 = _ema(closes, 50), _ema(closes, 200)

        rsi = None
        if len(closes) >= 15:
            changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
            gains = [max(0.0, value) for value in changes]
            losses = [max(0.0, -value) for value in changes]
            avg_gain = sum(gains[:14]) / 14.0
            avg_loss = sum(losses[:14]) / 14.0
            for gain, loss in zip(gains[14:], losses[14:]):
                avg_gain = (avg_gain * 13.0 + gain) / 14.0
                avg_loss = (avg_loss * 13.0 + loss) / 14.0
            rsi = 100.0 if avg_loss <= 1e-15 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

        macd_value = macd_signal = macd_hist = None
        if len(closes) >= 35:
            fast_values: list[float] = []
            slow_values: list[float] = []
            alpha_fast, alpha_slow = 2.0 / 13.0, 2.0 / 27.0
            fast = sum(closes[:12]) / 12.0
            slow = sum(closes[:26]) / 26.0
            for i, value in enumerate(closes):
                if i >= 12:
                    fast = alpha_fast * value + (1.0 - alpha_fast) * fast
                if i >= 26:
                    slow = alpha_slow * value + (1.0 - alpha_slow) * slow
                    fast_values.append(fast)
                    slow_values.append(slow)
            macd_series = [f - s for f, s in zip(fast_values, slow_values)]
            macd_value = macd_series[-1] if macd_series else None
            macd_signal = _ema(macd_series, 9)
            if macd_value is not None and macd_signal is not None:
                macd_hist = macd_value - macd_signal

        vwap = None
        if rows:
            recent = rows[-1440:]
            volume = sum(c.volume for c in recent)
            if volume > 0:
                vwap = sum(((c.high + c.low + c.close) / 3.0) * c.volume for c in recent) / volume

        atr_pct = None
        if len(rows) >= 15:
            trs = []
            for i in range(len(rows) - 14, len(rows)):
                c, prev = rows[i], rows[i - 1]
                trs.append(max(c.high - c.low, abs(c.high - prev.close), abs(c.low - prev.close)))
            atr = sum(trs) / len(trs)
            if close and close > 0:
                atr_pct = atr / close * 100.0

        volume_ratio = None
        if len(rows) >= 21:
            baseline = sum(c.volume for c in rows[-21:-1]) / 20.0
            volume_ratio = rows[-1].volume / baseline if baseline > 0 else None

        poc = None
        if rows:
            profile = rows[-200:]
            low_bound = min(c.low for c in profile)
            high_bound = max(c.high for c in profile)
            width = max((high_bound - low_bound) / 50.0, low_bound * 0.001, 1e-12)
            bins: dict[float, float] = {}
            for c in profile:
                typical = (c.high + c.low + c.close) / 3.0
                bucket = low_bound + round((typical - low_bound) / width) * width
                bins[bucket] = bins.get(bucket, 0.0) + c.volume
            if bins:
                poc = max(bins.items(), key=lambda item: item[1])[0]

        trend = "neutral"
        if all(v is not None for v in (e9, e21, e50, e200, close)):
            if e9 > e21 > e50 and close > e200 and (vwap is None or close >= vwap):
                trend = "bullish"
            elif e9 < e21 < e50 and close < e200 and (vwap is None or close <= vwap):
                trend = "bearish"

        momentum = "neutral"
        if macd_hist is not None and rsi is not None:
            if macd_hist > 0 and rsi > 50:
                momentum = "bullish"
            elif macd_hist < 0 and rsi < 50:
                momentum = "bearish"

        age5 = (
            max(0.0, current - (rows5[-1].open_time / 1000.0 + 300.0))
            if rows5 else None
        )
        ready = (
            len(rows) >= 200 and len(rows5) >= 50
            and age is not None and age <= 120.0
            and age5 is not None and age5 <= 600.0
        )
        vwap_distance = ((close / vwap) - 1.0) * 10_000.0 if close and vwap else None
        return IndicatorSnapshot(
            ready=ready,
            close=close,
            ema9=e9, ema21=e21, ema50=e50, ema200=e200,
            rsi14=rsi, macd=macd_value, macd_signal=macd_signal,
            macd_histogram=macd_hist, vwap=vwap,
            vwap_distance_bps=vwap_distance, atr14_pct=atr_pct,
            volume_ratio=volume_ratio, volume_profile_poc=poc,
            trend_bias=trend, momentum_bias=momentum,
            age_seconds=age,
            note=f"candles_1m={len(rows)}/200 candles_5m={len(rows5)}/50 trend={trend} momentum={momentum}",
        )


def fetch_recent_candles(symbol: str, interval: str, *, limit: int = 250, testnet: bool = False) -> list[Candle]:
    """Fetch only fully closed public Spot klines for indicator warm-up."""
    if interval not in {"1m", "5m"}:
        raise ValueError("supported indicator intervals are 1m and 5m")
    if not 10 <= int(limit) <= 1000:
        raise ValueError("limit must be in 10..1000")
    query = urllib.parse.urlencode({
        "symbol": symbol.upper(), "interval": interval, "limit": int(limit),
    })
    base = TESTNET_REST if testnet else MAINNET_REST
    request = urllib.request.Request(
        f"{base}/api/v3/klines?{query}",
        headers={"User-Agent": "NexoraQuant/0.1"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("invalid Binance kline response")
    now_ms = int(time.time() * 1000)
    candles: list[Candle] = []
    for row in payload:
        if not isinstance(row, list) or len(row) < 7:
            continue
        if int(row[6]) >= now_ms:
            continue
        candles.append(Candle(
            symbol=symbol.lower(), interval=interval, open_time=int(row[0]),
            open=float(row[1]), high=float(row[2]), low=float(row[3]),
            close=float(row[4]), volume=float(row[5]), closed=True,
            received_at=time.time(),
        ))
    return candles
