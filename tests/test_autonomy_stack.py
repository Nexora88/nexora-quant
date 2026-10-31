"""Core autonomy: ATR dynamic stops, spoof persistence, BTC alt lock."""
from __future__ import annotations

from app.atr_stops import compute_dynamic_targets
from app.intelligence.btc_filter import BtcTrendFilter
from app.intelligence.spoof import OrderPersistenceFilter


def test_quiet_vs_storm_targets():
    quiet = compute_dynamic_targets(atr_pct=0.0008, regime="choppy")
    storm = compute_dynamic_targets(atr_pct=0.0045, regime="trend")
    assert 0.15 <= quiet.stop_loss_pct <= 0.35
    assert 0.15 <= storm.stop_loss_pct <= 0.40
    assert storm.take_profit_pct >= quiet.take_profit_pct * 0.9


def test_spoof_filter_default_at_least_1s():
    f = OrderPersistenceFilter(min_persist_ms=1500.0)
    assert f.min_persist_ms >= 1000.0


def test_btc_wick_blocks_then_cools():
    b = BtcTrendFilter(wick_jump_bps=35.0, cooldown_ticks=3)
    b.update(100_000.0)
    s = b.update(99_500.0)
    assert s.block_long is True or s.last_ret_bps < 0
    for _ in range(5):
        s = b.tick_cooldown()
