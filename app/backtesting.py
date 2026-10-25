"""Deterministic OHLCV strategy research with next-bar execution and walk-forward evaluation.

This is a research simulator, not an exchange execution engine. Signals only use
completed candles and are applied after a configurable delay, avoiding same-bar
look-ahead. Costs are charged on position turnover.
"""
from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, pstdev
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def validate(self) -> "Candle":
        values = (self.open, self.high, self.low, self.close, self.volume)
        if isinstance(self.timestamp, bool) or not isinstance(self.timestamp, int) or self.timestamp < 0:
            raise ValueError("timestamp must be a non-negative integer")
        if not all(math.isfinite(v) for v in values):
            raise ValueError("OHLCV values must be finite")
        if min(self.open, self.high, self.low, self.close) <= 0 or self.volume < 0:
            raise ValueError("prices must be positive and volume non-negative")
        if self.high < max(self.open, self.close, self.low) or self.low > min(self.open, self.close, self.high):
            raise ValueError("invalid OHLC candle bounds")
        return self


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    fee_rate: float = 0.001
    slippage_bps: float = 2.0
    latency_bars: int = 0
    initial_cash: float = 10_000.0
    annualization_periods: int = 365
    train_fraction: float = 0.6
    min_train_bars: int = 100

    def validate(self) -> "BacktestConfig":
        if not 0 <= self.fee_rate < 0.1:
            raise ValueError("fee_rate must be in [0, 0.1)")
        if not math.isfinite(self.slippage_bps) or not 0 <= self.slippage_bps <= 1000:
            raise ValueError("slippage_bps must be in [0, 1000]")
        if isinstance(self.latency_bars, bool) or self.latency_bars < 0:
            raise ValueError("latency_bars must be >= 0")
        if not math.isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if self.annualization_periods < 1 or not 0 < self.train_fraction < 1:
            raise ValueError("invalid annualization_periods or train_fraction")
        if self.min_train_bars < 2:
            raise ValueError("min_train_bars must be >= 2")
        return self


def load_ohlcv_csv(path: str | Path) -> list[Candle]:
    """Load CSV columns timestamp,open,high,low,close and optional volume."""
    result: list[Candle] = []
    with open(path, newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"timestamp", "open", "high", "low", "close"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("CSV must contain timestamp,open,high,low,close columns")
        for row in reader:
            candle = Candle(
                timestamp=int(row["timestamp"]),
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
                volume=float(row.get("volume") or 0),
            ).validate()
            if result and candle.timestamp <= result[-1].timestamp:
                raise ValueError("timestamps must be strictly increasing")
            result.append(candle)
    if len(result) < 3:
        raise ValueError("at least 3 candles are required")
    return result


def _sma(values: Sequence[float], window: int, end: int) -> float | None:
    if end + 1 < window:
        return None
    return mean(values[end - window + 1 : end + 1])


def strategy_signal(strategy: str, closes: Sequence[float], index: int, params: dict[str, int]) -> int:
    """Return target exposure: 1 long or 0 flat, using data only through index."""
    if strategy == "buy_and_hold":
        return 1
    if strategy == "sma_cross":
        fast, slow = params.get("fast", 5), params.get("slow", 20)
        if fast < 1 or slow <= fast:
            raise ValueError("sma_cross requires 1 <= fast < slow")
        a, b = _sma(closes, fast, index), _sma(closes, slow, index)
        return int(a is not None and b is not None and a > b)
    if strategy == "momentum":
        lookback = params.get("lookback", 10)
        if lookback < 1:
            raise ValueError("momentum lookback must be >= 1")
        return int(index >= lookback and closes[index] > closes[index - lookback])
    if strategy == "mean_reversion":
        window = params.get("window", 20)
        entry_z = float(params.get("entry_z", 1))
        if window < 2 or not math.isfinite(entry_z) or entry_z <= 0:
            raise ValueError("mean reversion requires window >= 2 and entry_z > 0")
        if index + 1 < window:
            return 0
        sample = closes[index - window + 1 : index + 1]
        sigma = pstdev(sample)
        if sigma == 0:
            return 0
        z = (closes[index] - mean(sample)) / sigma
        return int(z < -entry_z)
    raise ValueError(f"unknown strategy: {strategy}")


def market_regime(closes: Sequence[float], index: int, window: int = 20) -> str:
    """Coarse descriptive regime: uptrend/downtrend/sideways plus high/normal vol."""
    if window < 2:
        raise ValueError("window must be >= 2")
    if index < window:
        return "unknown"
    sample = closes[index - window : index + 1]
    trend = sample[-1] / sample[0] - 1
    returns = [sample[i] / sample[i - 1] - 1 for i in range(1, len(sample))]
    vol = pstdev(returns) if returns else 0.0
    direction = "uptrend" if trend > 0.02 else "downtrend" if trend < -0.02 else "sideways"
    volatility = "high_vol" if vol > 0.02 else "normal_vol"
    return f"{direction}_{volatility}"


def _metrics(equity: Sequence[float], returns: Sequence[float], trades: int,
             fees_paid: float, regimes: dict[str, dict[str, float]],
             annualization_periods: int) -> dict:
    if not equity:
        raise ValueError("empty equity curve")
    peak = equity[0]
    max_drawdown = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - value) / peak)
    avg = mean(returns) if returns else 0.0
    vol = pstdev(returns) if len(returns) > 1 else 0.0
    gross_profit = sum(x for x in returns if x > 0)
    gross_loss = -sum(x for x in returns if x < 0)
    return {
        "initial_equity": equity[0],
        "final_equity": equity[-1],
        "net_return_pct": (equity[-1] / equity[0] - 1) * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "sharpe_annualized": (avg / vol * math.sqrt(annualization_periods)) if vol > 0 else 0.0,
        "trade_count": trades,
        "fees_and_slippage_paid": fees_paid,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else (math.inf if gross_profit else 0.0),
        "regime_returns_pct": regimes,
    }


def backtest(candles: Sequence[Candle], strategy: str, params: dict[str, int] | None = None,
             config: BacktestConfig | None = None) -> dict:
    """Run a long-or-flat close-to-close test with delayed, next-bar signal application."""
    cfg = (config or BacktestConfig()).validate()
    rows = list(candles)
    if len(rows) < 3:
        raise ValueError("at least 3 candles are required")
    for i, candle in enumerate(rows):
        candle.validate()
        if i and candle.timestamp <= rows[i - 1].timestamp:
            raise ValueError("timestamps must be strictly increasing")
    params = params or {}
    closes = [c.close for c in rows]
    position = 0
    equity = cfg.initial_cash
    curve = [equity]
    period_returns: list[float] = []
    trades = 0
    costs_total = 0.0
    regime_pnl: dict[str, list[float]] = {}
    slip = cfg.slippage_bps / 10_000
    for i in range(1, len(rows)):
        # Signal from a completed prior candle; latency_bars delays it further.
        signal_index = i - 1 - cfg.latency_bars
        target = strategy_signal(strategy, closes, signal_index, params) if signal_index >= 0 else 0
        turnover = abs(target - position)
        if turnover:
            cost = equity * turnover * (cfg.fee_rate + slip)
            equity -= cost
            costs_total += cost
            trades += 1
        position = target
        period_return = rows[i].close / rows[i - 1].close - 1
        pnl_return = period_return * position
        equity *= max(0.0, 1 + pnl_return)
        period_returns.append(pnl_return)
        regime = market_regime(closes, i - 1)
        regime_pnl.setdefault(regime, []).append(pnl_return)
        curve.append(equity)
        position = target
    regime_returns = {
        name: {"bars": float(len(vals)), "return_pct": (math.prod(1 + v for v in vals) - 1) * 100}
        for name, vals in regime_pnl.items()
    }
    result = _metrics(curve, period_returns, trades, costs_total, regime_returns, cfg.annualization_periods)
    result.update({"strategy": strategy, "parameters": params, "bars": len(rows),
                   "latency_bars": cfg.latency_bars, "fee_rate": cfg.fee_rate,
                   "slippage_bps": cfg.slippage_bps})
    return result


def compare_strategies(candles: Sequence[Candle], candidates: Iterable[dict],
                       config: BacktestConfig | None = None) -> list[dict]:
    """Evaluate candidates on the same data/cost assumptions, ranked by test return."""
    results = [
        backtest(candles, item["strategy"], item.get("params", {}), config)
        for item in candidates
    ]
    return sorted(results, key=lambda row: row["net_return_pct"], reverse=True)


def walk_forward(candles: Sequence[Candle], candidates: Iterable[dict],
                 config: BacktestConfig | None = None) -> dict:
    """Use the first chronological segment for selection and later unseen segment for scoring."""
    cfg = (config or BacktestConfig()).validate()
    rows = list(candles)
    split = int(len(rows) * cfg.train_fraction)
    if split < cfg.min_train_bars or len(rows) - split < 3:
        raise ValueError("not enough candles for configured train/test split")
    choices = list(candidates)
    if not choices:
        raise ValueError("at least one strategy candidate is required")
    train_config = BacktestConfig(**{**asdict(cfg), "initial_cash": cfg.initial_cash})
    train = compare_strategies(rows[:split], choices, train_config)
    winner = train[0]
    # Test segment is scored independently; indicator warm-up is intentionally local
    # to avoid accidentally sharing future test observations with training.
    test = backtest(rows[split:], winner["strategy"], winner["parameters"], cfg)
    return {
        "split_index": split,
        "train_bars": split,
        "test_bars": len(rows) - split,
        "selected_strategy": winner["strategy"],
        "selected_parameters": winner["parameters"],
        "training_results": train,
        "unseen_test_result": test,
        "warning": "One chronological holdout is not proof of robustness; repeat across rolling windows and assets.",
    }


def rolling_walk_forward(
    candles: Sequence[Candle],
    candidates: Iterable[dict],
    *,
    train_bars: int,
    test_bars: int,
    step_bars: int | None = None,
    config: BacktestConfig | None = None,
) -> dict:
    """Evaluate repeated chronological train/test windows without shuffling data.

    Each window selects a candidate using only its training segment, then scores
    that selection on the immediately following unseen segment. Test windows never
    overlap by default; step_bars may be smaller for overlapping diagnostic windows.
    Metrics are per-window and aggregated, not a promise of future performance.
    """
    cfg = (config or BacktestConfig()).validate()
    rows = list(candles)
    choices = list(candidates)
    step = test_bars if step_bars is None else step_bars
    if train_bars < cfg.min_train_bars:
        raise ValueError("train_bars must be >= configured min_train_bars")
    if test_bars < 2 or step < 1:
        raise ValueError("test_bars must be >= 2 and step_bars >= 1")
    if not choices:
        raise ValueError("at least one strategy candidate is required")
    if train_bars + test_bars > len(rows):
        raise ValueError("not enough candles for one rolling train/test window")

    windows: list[dict] = []
    start = 0
    while start + train_bars + test_bars <= len(rows):
        train = rows[start : start + train_bars]
        test_start = start + train_bars
        test = rows[test_start : test_start + test_bars]
        train_results = compare_strategies(train, choices, cfg)
        winner = train_results[0]
        test_result = backtest(test, winner["strategy"], winner["parameters"], cfg)
        windows.append({
            "train_start": train[0].timestamp,
            "train_end": train[-1].timestamp,
            "test_start": test[0].timestamp,
            "test_end": test[-1].timestamp,
            "selected_strategy": winner["strategy"],
            "selected_parameters": winner["parameters"],
            "training_net_return_pct": winner["net_return_pct"],
            "test_result": test_result,
        })
        start += step

    if not windows:
        raise ValueError("no complete rolling windows available")
    test_returns = [w["test_result"]["net_return_pct"] for w in windows]
    drawdowns = [w["test_result"]["max_drawdown_pct"] for w in windows]
    return {
        "windows": windows,
        "window_count": len(windows),
        "mean_test_return_pct": mean(test_returns),
        "median_test_return_pct": median(test_returns),
        "positive_test_window_fraction": sum(r > 0 for r in test_returns) / len(test_returns),
        "worst_test_return_pct": min(test_returns),
        "worst_max_drawdown_pct": max(drawdowns),
        "warning": (
            "Rolling windows are historical diagnostics, not a guarantee. "
            "Test-window indicator warm-up is local, and bar-based costs/latency "
            "do not model full order-book execution or market impact."
        ),
    }
