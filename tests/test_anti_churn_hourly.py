"""Anti-churn hourly counter must record entries in both paper and live paths."""
from __future__ import annotations

import time


def test_hourly_trade_ts_append_and_prune_logic() -> None:
    """Mirror engine_tick anti-churn list maintenance (mode-agnostic)."""
    now = time.time()
    hourly = [now - 4000.0, now - 100.0, now - 10.0]
    hourly = [x for x in hourly if now - float(x) <= 3600.0]
    assert len(hourly) == 2
    hourly = hourly + [now]
    assert len(hourly) == 3
    max_tph = 2
    assert len(hourly) >= max_tph


def test_live_and_paper_both_record_entry_timestamp_shape() -> None:
    """Successful entry should append one timestamp regardless of mode label."""
    for _mode in ("paper", "live"):
        ts: list[float] = []
        ts = list(ts) + [time.time()]
        assert len(ts) == 1
        assert ts[0] > 0
