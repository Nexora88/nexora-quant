"""Autonomous multi-symbol ranking."""
from __future__ import annotations

from app.simulation import ExecutionSimulator
from app.symbol_router import SymbolRouter


def test_router_picks_highest_tradeable_score():
    r = SymbolRouter(min_score=0.5, max_spoof=0.55)
    r.update("solusdt", score=0.9, regime="trend", spoof_score=0.1, btc_blocked=False)
    r.update("ethusdt", score=0.7, regime="trend", spoof_score=0.1, btc_blocked=False)
    # Mild chop + weak score blocked; strong score may still rank.
    r.update("bnbusdt", score=0.52, regime="choppy", spoof_score=0.1, btc_blocked=False)
    best = r.select_best()
    assert best is not None
    assert best.symbol == "solusdt"
    assert r.should_enter_on("solusdt")
    assert not r.should_enter_on("ethusdt")


def test_router_blocks_spoof_and_btc():
    r = SymbolRouter(min_score=0.5, max_spoof=0.55)
    r.update("solusdt", score=0.99, regime="trend", spoof_score=0.9, btc_blocked=False)
    r.update("ethusdt", score=0.8, regime="trend", spoof_score=0.1, btc_blocked=True)
    assert r.select_best() is None


def test_vol_stress_multiplier_scales():
    sim = ExecutionSimulator(slippage_bps=1, latency_ms=0, seed=1, stop_stress_multiplier=2.0)
    sim.set_volatility_bps(0)
    calm = sim.effective_stress_multiplier()
    sim.set_volatility_bps(50)
    hot = sim.effective_stress_multiplier()
    assert hot > calm
