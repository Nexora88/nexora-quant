from datetime import datetime, timezone

from app.events import TradeTick
from app.trade_flow import TradeFlowTracker


def trade(ts: float, *, buyer_is_maker: bool, qty: float = 1.0) -> TradeTick:
    return TradeTick(
        "btcusdt", 100.0, qty, buyer_is_maker,
        datetime.fromtimestamp(ts, tz=timezone.utc),
    )


def test_aggressor_side_sign_and_cvd():
    tracker = TradeFlowTracker(min_trades=2, max_age_seconds=3.0)
    tracker.update(trade(100.0, buyer_is_maker=False), now=100.0)
    snap = tracker.update(trade(100.1, buyer_is_maker=True, qty=0.5), now=100.1)
    assert snap.buy_qty == 1.0
    assert snap.sell_qty == 0.5
    assert snap.delta_qty == 0.5
    assert snap.cvd == 0.5
    assert snap.bullish


def test_stale_or_warming_trade_flow_is_not_ready():
    tracker = TradeFlowTracker(min_trades=3, max_age_seconds=1.0)
    tracker.update(trade(100.0, buyer_is_maker=False), now=100.0)
    assert not tracker.snapshot(now=100.1).ready
    assert not tracker.snapshot(now=102.0).ready


def test_out_of_order_trade_does_not_refresh_feed():
    tracker = TradeFlowTracker(min_trades=1, max_age_seconds=1.0)
    tracker.update(trade(100.0, buyer_is_maker=False), now=100.0)
    snap = tracker.update(trade(99.0, buyer_is_maker=False), now=100.2)
    assert snap.trades == 1
    assert snap.cvd == 1.0
    assert abs(snap.age_seconds - 0.2) < 1e-9


def test_window_delta_expires_but_cvd_is_cumulative():
    tracker = TradeFlowTracker(window_seconds=2.0, min_trades=1, max_age_seconds=5.0)
    tracker.update(trade(100.0, buyer_is_maker=False), now=100.0)
    tracker.update(trade(101.0, buyer_is_maker=True, qty=0.25), now=101.0)
    snap = tracker.snapshot(now=103.1)
    assert snap.trades == 0
    assert snap.delta_qty == 0.0
    assert snap.cvd == 0.75
    assert not snap.ready
