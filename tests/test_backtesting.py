import math

import pytest

from app.backtesting import (
    BacktestConfig, Candle, backtest, compare_strategies, market_regime, rolling_walk_forward, validate_multiple_assets, walk_forward,
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


def test_rolling_walk_forward_reports_multiple_unseen_windows():
    rows = candles_from_closes([100 + i * 0.1 + math.sin(i / 4) for i in range(180)])
    candidates = [
        {"strategy": "buy_and_hold", "params": {}},
        {"strategy": "momentum", "params": {"lookback": 5}},
        {"strategy": "sma_cross", "params": {"fast": 3, "slow": 10}},
    ]
    report = rolling_walk_forward(
        rows, candidates, train_bars=80, test_bars=20, step_bars=20,
        config=BacktestConfig(min_train_bars=50, fee_rate=0.001, slippage_bps=2),
    )
    assert report["window_count"] == 5
    assert len(report["windows"]) == 5
    assert 0 <= report["positive_test_window_fraction"] <= 1
    assert report["worst_max_drawdown_pct"] >= 0
    assert "not a guarantee" in report["warning"]


def test_rolling_walk_forward_rejects_invalid_window_sizes():
    rows = candles_from_closes([100 + i for i in range(40)])
    with pytest.raises(ValueError):
        rolling_walk_forward(rows, [{"strategy": "buy_and_hold", "params": {}}],
                             train_bars=30, test_bars=20)



def test_regime_adaptive_and_multiple_asset_validation():
    rows_a = candles_from_closes([100 + i * 0.15 + math.sin(i / 5) for i in range(180)])
    rows_b = candles_from_closes([80 + i * 0.08 + math.sin(i / 4) for i in range(180)])
    candidates = [
        {"strategy": "regime_adaptive", "params": {
            "regime_window": 20, "momentum_lookback": 8, "mean_window": 15, "entry_z": 1,
        }},
        {"strategy": "buy_and_hold", "params": {}},
    ]
    result = backtest(rows_a, "regime_adaptive", candidates[0]["params"],
                      BacktestConfig(fee_rate=0.001, slippage_bps=3))
    assert result["strategy"] == "regime_adaptive"
    assert "worst_period_return_pct" in result
    assert "expected_shortfall_5_pct" in result
    report = validate_multiple_assets(
        {"ASSET_A": rows_a, "ASSET_B": rows_b}, candidates,
        train_bars=100, test_bars=20,
        config=BacktestConfig(min_train_bars=50, fee_rate=0.001, slippage_bps=3),
    )
    assert report["asset_count"] == 2
    assert "worst_asset_window_return_pct" in report
    assert "worst_asset_max_drawdown_pct" in report
