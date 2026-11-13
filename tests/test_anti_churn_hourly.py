"""Anti-churn hourly counter: single source of truth is RuntimeState.record_fill (buy)."""
from __future__ import annotations

import time

from app.state import RuntimeState


def test_record_fill_buy_appends_once_and_prunes() -> None:
    st = RuntimeState()
    now = time.time()
    st.hourly_trade_ts = [now - 4000.0, now - 100.0]
    st.record_fill({"side": "buy", "fee_usdt": 0.01, "symbol": "btcusdt"})
    # 4000s-old pruned; 100s-old kept; new append → 2
    assert len(st.hourly_trade_ts) == 2
    assert st.hourly_trade_ts[-1] >= now - 2.0
    assert st.last_entry_at is not None
    assert st.position_opened_at is not None


def test_record_fill_is_single_source_no_double_count() -> None:
    """Engine must not also append; two record_fill buys → exactly 2 stamps."""
    st = RuntimeState()
    st.record_fill({"side": "buy", "fee_usdt": 0.01})
    st.record_fill({"side": "buy", "fee_usdt": 0.01})
    assert len(st.hourly_trade_ts) == 2


def test_sell_does_not_append_hourly() -> None:
    st = RuntimeState()
    st.record_fill({"side": "buy", "fee_usdt": 0.01})
    st.record_fill({"side": "sell", "fee_usdt": 0.01, "pnl_usdt": 0.5})
    assert len(st.hourly_trade_ts) == 1
    assert st.closed_trade_count == 1


def test_max_trades_per_hour_gate_shape() -> None:
    now = time.time()
    hourly = [now - 4000.0, now - 100.0, now - 10.0]
    hourly = [x for x in hourly if now - float(x) <= 3600.0]
    assert len(hourly) == 2
    max_tph = 2
    assert len(hourly) >= max_tph


def test_session_expectancy_and_maker_stats() -> None:
    st = RuntimeState()
    assert st.session_expectancy()["n"] == 0
    st.record_fill({"side": "buy", "fee_usdt": 0.02})
    st.record_fill({"side": "sell", "fee_usdt": 0.02, "pnl_usdt": 0.5})
    st.record_fill({"side": "buy", "fee_usdt": 0.02})
    st.record_fill({"side": "sell", "fee_usdt": 0.02, "pnl_usdt": -0.2})
    exp = st.session_expectancy()
    assert exp["n"] == 2
    assert abs(float(exp["expectancy_usdt"]) - 0.15) < 1e-9
    assert exp["win_rate"] == 0.5
    st.maker_entry_attempts = 10
    st.maker_entry_fills = 6
    st.maker_entry_timeouts = 4
    ms = st.maker_stats()
    assert ms["timeout_rate"] == 0.4
    assert ms["weak_maker_path"] is True
    snap = st.snapshot()
    assert "session_expectancy" in snap
    assert "maker_stats" in snap
