from app.order_flow import OrderFlowAccumulator
from app.replay_context import ReplayMarketContext


def _seed(context: ReplayMarketContext, symbol: str, base_ms: int) -> None:
    for interval, count, step in (("1m", 250, 60_000), ("5m", 100, 300_000)):
        for i in range(count):
            close = 100.0 + i * 0.02
            context.update_kline({
                "symbol": symbol,
                "interval": interval,
                "open_time": base_ms - (count - i) * step,
                "open": close,
                "high": close + 0.04,
                "low": close - 0.01,
                "close": close,
                "volume": 100.0,
                "closed": True,
            }, base_ms / 1000.0)


def test_order_flow_accumulator_uses_replay_event_time_not_wall_clock():
    tracker = OrderFlowAccumulator(hold_seconds=1.8, min_samples=7, min_abs_pressure=0.14)
    states = [
        tracker.update(imbalance=0.9, timestamp=1000.0 + i * 0.3)
        for i in range(9)
    ]
    assert states[-1].ready
    assert states[-1].pressure > 0.14


def test_replay_context_requires_trade_book_indicator_and_macro_confirmation():
    base_ms = 1_700_000_000_000
    base_time = base_ms / 1000.0
    context = ReplayMarketContext(["solusdt"])
    for symbol in ("btcusdt", "ethusdt", "solusdt"):
        _seed(context, symbol, base_ms)

    for i in range(24):
        context.update_trade({
            "symbol": "solusdt", "price": 100.0,
            "quantity": 0.1, "buyer_is_maker": False,
        }, base_time - 1.0 + i * 0.04)

    payload = {
        "symbol": "solusdt",
        "bids": [[99.99 - i * 0.01, 20.0 if i == 0 else 5.0] for i in range(20)],
        "asks": [[100.01 + i * 0.01, 2.0 if i == 0 else 3.0] for i in range(20)],
    }
    depth = None
    for i in range(11):
        depth = context.update_depth(
            payload, base_time - 2.0 + i * 0.3,
            imbalance=0.9, micro_premium_bps=0.0,
        )

    blockers, details = context.entry_blockers("solusdt", base_time + 1.0, depth)
    assert blockers == [], (blockers, details["book_flow"], details["trade_flow"], details["fused_flow"])
    assert details["indicator"].ready
    assert details["trade_flow"].ready
    assert details["book_flow"].ready
    assert details["macro"]["ready"] is True


def test_replay_context_fails_closed_without_btc_macro_history():
    base_ms = 1_700_000_000_000
    base_time = base_ms / 1000.0
    context = ReplayMarketContext(["adausdt"])
    _seed(context, "adausdt", base_ms)
    _seed(context, "ethusdt", base_ms)
    for i in range(24):
        context.update_trade({
            "symbol": "adausdt", "price": 100.0,
            "quantity": 0.1, "buyer_is_maker": False,
        }, base_time - 1.0 + i * 0.04)
    payload = {
        "symbol": "adausdt",
        "bids": [[99.99 - i * 0.01, 20.0 if i == 0 else 5.0] for i in range(20)],
        "asks": [[100.01 + i * 0.01, 2.0 if i == 0 else 3.0] for i in range(20)],
    }
    depth = None
    for i in range(11):
        depth = context.update_depth(
            payload, base_time - 2.0 + i * 0.3,
            imbalance=0.9, micro_premium_bps=0.0,
        )
    blockers, _ = context.entry_blockers("adausdt", base_time + 1.0, depth)
    assert "btc_context_warming_or_stale" in blockers



def test_replay_spoof_filter_requires_1500ms_level_persistence():
    context = ReplayMarketContext(["btcusdt"])
    payload = {
        "symbol": "btcusdt",
        "bids": [[99.99 - i * 0.01, 10.0] for i in range(20)],
        "asks": [[100.01 + i * 0.01, 10.0] for i in range(20)],
    }
    first = context.update_depth(
        payload, 1000.0, imbalance=0.8, micro_premium_bps=0.0,
    )
    before_persist = context.update_depth(
        payload, 1001.4, imbalance=0.8, micro_premium_bps=0.0,
    )
    persisted = context.update_depth(
        payload, 1001.6, imbalance=0.8, micro_premium_bps=0.0,
    )
    assert first.spoof_score == 1.0
    assert before_persist.spoof_score == 1.0
    assert persisted.spoof_score == 0.0
    assert persisted.stable_bid_usdt > 0
    assert persisted.stable_ask_usdt > 0
