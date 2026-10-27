"""Liquidity gate, regime TP/SL, vol sizing."""
from __future__ import annotations

from app.autonomous_policy import (
    assess_liquidity,
    regime_targets,
    vol_adjusted_notional,
)
from app.dynamic_gate import DynamicKellyGate
from app.symbol_router import SymbolRouter


def test_shallow_book_rejected():
    thin = [(100.0, 0.01)] * 5
    v = assess_liquidity(symbol="solusdt", bids=thin, asks=thin, spread_bps=3.0)
    assert v.ok is False


def test_deep_book_accepted():
    deep = [(100.0, 50.0)] * 15
    v = assess_liquidity(symbol="btcusdt", bids=deep, asks=deep, spread_bps=2.0)
    assert v.ok is True
    assert v.depth_usdt > 40_000


def test_trend_widens_tp():
    t = regime_targets(regime="trend", base_tp=1.2, base_sl=0.35, vol_bps=30)
    assert t.take_profit_pct >= 2.0
    assert t.take_profit_pct >= t.stop_loss_pct * 1.5


def test_chop_tightens_and_shrinks_size():
    t = regime_targets(regime="choppy", base_tp=1.2, base_sl=0.35, vol_bps=10)
    assert t.take_profit_pct < 1.0
    assert t.size_scale < 1.0


def test_high_vol_crushes_size():
    calm = regime_targets(regime="unknown", vol_bps=5)
    wild = regime_targets(regime="unknown", vol_bps=55)
    assert wild.size_scale < calm.size_scale


def test_kelly_respects_size_scale():
    k = DynamicKellyGate(max_fraction=0.25, min_order_usdt=5, max_order_usdt=100)
    for _ in range(12):
        k.record_pnl(2.0)
        k.record_pnl(-1.0)
    full = k.size(free_usdt=1000, size_scale=1.0)
    small = k.size(free_usdt=1000, size_scale=0.3)
    assert small.notional_usdt < full.notional_usdt or small.notional_usdt == 0


def test_router_prefers_deeper_book_on_tie():
    r = SymbolRouter(min_score=0.5)
    r.update("solusdt", score=0.8, regime="trend", liquid=True, depth_usdt=5_000)
    r.update("ethusdt", score=0.8, regime="trend", liquid=True, depth_usdt=50_000)
    best = r.select_best()
    assert best is not None
    assert best.symbol == "ethusdt"


def test_vol_adjusted_notional_floor():
    assert vol_adjusted_notional(
        base_notional=4.0, size_scale=1.0, min_order_usdt=5.0, max_order_usdt=25.0
    ) == 0.0
