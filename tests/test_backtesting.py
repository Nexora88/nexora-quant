import math

import pytest

from app.backtesting import (
    BacktestConfig, Candle, backtest, compare_strategies, market_regime, walk_forward,
)


def candles_from_closes(closes):
    return [
        Candle(i, value, value * 1.01, value * 0.99, value, 10.0)
        for i, value in enumerate(closes)
    ]


def test_backtest_charges_costs_and_reports_drawdown():
    rows = candles_from_closes([100, 102, 104, 98, 96, 101, 105, 103, 110, 112])
    free = backtest(rows, "buy_and_hold", config=BacktestConfig(fee_rate=0, slippage_bps=0))
    costs = backtest(rows, "buy_and_hold", config=BacktestConfig(fee_rate=0.001, slippage_bps=5))
    assert costs["final_equity"] < free["final_equity"]
    assert costs["fees_and_slippage_paid"] > 0
    assert costs["max_drawdown_pct"] > 0
    assert costs["bars"] == len(rows)


def test_signal_is_delayed_and_unknown_strategy_rejected():
    rows = candles_from_closes([100 + i for i in range(40)])
    immediate = backtest(rows, "momentum", {"lookback": 3},
                         BacktestConfig(fee_rate=0, slippage_bps=0, latency_bars=0))
    delayed = backtest(rows, "momentum", {"lookback": 3},
                       BacktestConfig(fee_rate=0, slippage_bps=0, latency_bars=2))
    assert immediate["final_equity"] >= delayed["final_equity"]
    with pytest.raises(ValueError):
        backtest(rows, "magic_alpha")


def test_compare_strategies_and_walk_forward_unseen_period():
    closes = [100 + i * 0.2 + math.sin(i / 3) for i in range(240)]
    rows = candles_from_closes(closes)
    candidates = [
        {"strategy": "buy_and_hold", "params": {}},
        {"strategy": "momentum", "params": {"lookback": 8}},
        {"strategy": "sma_cross", "params": {"fast": 4, "slow": 15}},
        {"strategy": "mean_reversion", "params": {"window": 15, "entry_z": 1}},
    ]
    ranked = compare_strategies(rows, candidates)
    assert len(ranked) == 4
    report = walk_forward(rows, candidates, BacktestConfig(train_fraction=0.65, min_train_bars=100))
    assert report["train_bars"] + report["test_bars"] == len(rows)
    assert report["unseen_test_result"]["bars"] == len(rows) - report["split_index"]
    assert "not proof" in report["warning"]


def test_validation_rejects_bad_candles_and_config():
    with pytest.raises(ValueError):
        Candle(1, 10, 9, 8, 10).validate()
    with pytest.raises(ValueError):
        BacktestConfig(fee_rate=-1).validate()
    with pytest.raises(ValueError):
        market_regime([1, 2], 1, window=1)
