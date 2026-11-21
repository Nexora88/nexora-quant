"""Cross-symbol mutable state isolation regressions."""

from app import engine_tick
from app.engine_setup import state


def test_tracker_and_runtime_diagnostics_are_isolated_per_symbol():
    engine_tick._symbol_contexts.clear()
    engine_tick._symbol_order_flows.clear()
    engine_tick._symbol_spoof_filters.clear()
    engine_tick._active_symbol_key = None
    state.symbol_runtime_state.clear()

    engine_tick._activate_symbol_context("btcusdt")
    btc_ctx = engine_tick._symbol_contexts["btcusdt"]
    state.score_ema = 0.71
    state._score_ema_seeded = True
    state.last_trade_flow = {"symbol": "btcusdt", "delta_ratio": 0.8}
    state.last_analysis = {"symbol": "btcusdt", "score": 0.71}
    state.blockers_live = ["btc_only_blocker"]

    engine_tick._activate_symbol_context("ethusdt")
    eth_ctx = engine_tick._symbol_contexts["ethusdt"]
    assert all(btc_ctx[name] is not eth_ctx[name] for name in btc_ctx)
    assert state.score_ema == 0.0
    assert state._score_ema_seeded is False
    assert state.last_trade_flow is None
    assert state.last_analysis is None
    assert state.blockers_live == []

    state.score_ema = 0.24
    state.last_trade_flow = {"symbol": "ethusdt", "delta_ratio": -0.2}
    engine_tick._activate_symbol_context("btcusdt")
    assert state.score_ema == 0.71
    assert state.last_trade_flow == {"symbol": "btcusdt", "delta_ratio": 0.8}
    assert state.last_analysis == {"symbol": "btcusdt", "score": 0.71}
    assert state.blockers_live == ["btc_only_blocker"]

    engine_tick._activate_symbol_context("ethusdt")
    assert state.score_ema == 0.24
    assert state.last_trade_flow == {"symbol": "ethusdt", "delta_ratio": -0.2}
