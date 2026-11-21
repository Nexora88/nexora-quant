from app.market_indicators import Candle, MarketIndicatorTracker


def candle(
    interval: str, index: int, now: float, *, total: int = 220,
    close: float | None = None, closed: bool = True,
) -> Candle:
    price = close if close is not None else 100.0 + index * 0.1 + index * index * 0.0005
    seconds = 60 if interval == "1m" else 300
    return Candle(
        symbol="btcusdt",
        interval=interval,
        open_time=int((now - (total - index) * seconds) * 1000),
        open=price - 0.05,
        high=price + 0.15,
        low=price - 0.15,
        close=price,
        volume=10.0,
        closed=closed,
    )


def test_closed_candles_produce_grouped_indicators():
    now = 2_000_000_000.0
    tracker = MarketIndicatorTracker()
    tracker.seed(
        [candle("1m", i, now) for i in range(220)]
        + [candle("5m", i, now, total=60) for i in range(60)]
    )
    snap = tracker.snapshot(now=now)
    assert snap.ready
    assert snap.ema9 > snap.ema21 > snap.ema50 > snap.ema200
    assert snap.rsi14 == 100.0
    assert snap.macd_histogram > 0
    assert snap.vwap is not None
    assert snap.atr14_pct > 0
    assert snap.volume_ratio == 1.0
    assert snap.volume_profile_poc is not None
    assert snap.trend_bias == "bullish"
    assert snap.momentum_bias == "bullish"


def test_closed_candle_freshness_uses_close_time_not_open_time():
    now = 2_000_000_000.0
    tracker = MarketIndicatorTracker()
    tracker.seed(
        [candle("1m", i, now) for i in range(220)]
        + [candle("5m", i, now, total=60) for i in range(60)]
    )
    snap = tracker.snapshot(now=now)
    assert snap.ready
    assert snap.age_seconds == 0.0


def test_forming_and_out_of_order_candles_are_ignored():
    now = 2_000_000_000.0
    tracker = MarketIndicatorTracker()
    first = candle("1m", 1, now)
    tracker.update(first)
    tracker.update(candle("1m", 2, now, closed=False))
    tracker.update(first)
    assert len(tracker.closes("1m")) == 1


def test_indicator_warmup_fails_closed_without_full_history():
    now = 2_000_000_000.0
    tracker = MarketIndicatorTracker()
    tracker.seed([candle("1m", i, now) for i in range(30)])
    snap = tracker.snapshot(now=now)
    assert not snap.ready
    assert snap.ema200 is None


def test_relative_strength_and_aligned_return_correlation():
    now = 2_000_000_000.0
    asset = MarketIndicatorTracker()
    btc = MarketIndicatorTracker()
    for i in range(40):
        ts = int((now - (40 - i) * 60) * 1000)
        a_price = 100.0 + i * 0.2 + i * i * 0.001
        b_price = 200.0 + i * 0.4 + i * i * 0.002
        asset.update(Candle("solusdt", "1m", ts, a_price, a_price + 0.2, a_price - 0.2, a_price, 10.0))
        btc.update(Candle("btcusdt", "1m", ts, b_price, b_price + 0.2, b_price - 0.2, b_price, 10.0))
    assert asset.return_bps(bars=5) is not None
    assert btc.return_bps(bars=5) is not None
    assert asset.correlation_with(btc, periods=30) > 0.99
