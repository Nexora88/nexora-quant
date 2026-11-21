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
    assert r.select_best_entry() is None
    assert not r.should_enter_on("ethusdt")


def test_vol_stress_multiplier_scales():
    sim = ExecutionSimulator(slippage_bps=1, latency_ms=0, seed=1, stop_stress_multiplier=2.0)
    sim.set_volatility_bps(0)
    calm = sim.effective_stress_multiplier()
    sim.set_volatility_bps(50)
    hot = sim.effective_stress_multiplier()
    assert hot > calm

def test_router_never_selects_stale_symbol_after_stream_stops():
    from datetime import datetime, timedelta, timezone

    r = SymbolRouter(min_score=0.5, max_age_seconds=1.0)
    r.update("solusdt", score=0.99, regime="trend")
    r.update("ethusdt", score=0.75, regime="trend")
    r._board["solusdt"].updated_at = (
        datetime.now(timezone.utc) - timedelta(seconds=5)
    ).isoformat()

    best = r.select_best()
    assert best is not None
    assert best.symbol == "ethusdt"
    assert all(row["symbol"] != "solusdt" for row in r.leaderboard())



def test_scan_prefilter_never_authorizes_trade_without_full_analysis():
    r = SymbolRouter(min_score=0.30)
    row = r.update_scan("ethusdt", score=0.99, liquid=True)
    assert row.scan_score == 0.99
    assert row.analysis_confirmed is False
    assert row.tradeable is False
    assert r.select_best() is not None  # may be selected for deeper analysis
    assert r.select_best_entry() is None
    assert not r.should_enter_on("ethusdt")


def test_full_analysis_must_be_entry_ready_and_pass_router_gates():
    r = SymbolRouter(min_score=0.30)
    r.update_scan("ethusdt", score=0.99)
    row = r.update_analysis(
        "ethusdt", score=0.29, regime="trend", entry_ready=False,
    )
    assert row.analysis_confirmed is True
    assert row.entry_ready is False
    assert r.select_best_entry() is None
    assert not r.should_enter_on("ethusdt")
    row = r.update_analysis(
        "ethusdt", score=0.45, regime="trend", entry_ready=True,
    )
    assert row.scan_score == 0.99
    assert row.entry_ready is True
    assert r.select_best().symbol == "ethusdt"


def test_scan_refresh_does_not_make_old_analysis_fresh():
    from datetime import datetime, timedelta, timezone
    r = SymbolRouter(min_score=0.30, max_age_seconds=1.0)
    r.update_analysis("ethusdt", score=0.8, regime="trend", entry_ready=True)
    old = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    r._board["ethusdt"].updated_at = old
    r.update_scan("ethusdt", score=1.0)
    assert r.select_best_entry() is None
    assert not r.should_enter_on("ethusdt")


def test_scan_score_only_selects_a_candidate_and_full_analysis_controls_entry():
    r = SymbolRouter(min_score=0.30, max_age_seconds=8.0)
    r.update_scan("ethusdt", score=0.95, liquid=True, reasons=["scan_obi=0.90"])
    r.update_scan("solusdt", score=0.72, liquid=True, reasons=["scan_obi=0.70"])

    # Highest scan score nominates ETH, but it is not an entry authorization.
    candidate = r.select_best()
    assert candidate is not None and candidate.symbol == "ethusdt"
    assert candidate.tradeable is False
    assert candidate.analysis_confirmed is False

    # The real engine rejects ETH; the next untested scan candidate is selected.
    r.update_analysis("ethusdt", score=0.21, regime="trend", entry_ready=False,
                      reasons=["momentum_1m_not_positive", "score_below_0.3"])
    candidate = r.select_best()
    assert candidate is not None and candidate.symbol == "solusdt"

    # A full positive decision, not the scan score, makes a coin entry-selectable.
    r.update_analysis("solusdt", score=0.64, regime="trend", entry_ready=True)
    best = r.select_best()
    assert best is not None and best.symbol == "solusdt"
    assert best.analysis_confirmed and best.entry_ready and best.tradeable


def test_scan_refresh_does_not_overwrite_fresh_full_analysis():
    r = SymbolRouter(min_score=0.30)
    r.update_scan("adausdt", score=0.88, liquid=True)
    r.update_analysis("adausdt", score=0.19, regime="trend", entry_ready=False,
                      reasons=["momentum_1m_not_positive"])
    r.update_scan("adausdt", score=0.99, liquid=True)
    row = r._board["adausdt"]
    assert row.analysis_confirmed is True
    assert row.entry_ready is False
    assert row.score == 0.19
    assert row.scan_score == 0.99
