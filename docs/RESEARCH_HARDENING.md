# Research hardening (L2 backtest, storage, impact, auth)

## 1. L2 event-driven backtest

```python
from app.l2_backtest import L2BacktestConfig, run_l2_backtest, summarize_l2_result

result = run_l2_backtest("data/market-history.jsonl.gz", L2BacktestConfig(entry_min_score=0.5))
print(summarize_l2_result(result))
```

Replays `MarketHistoryWriter` gzip JSONL in timestamp order, scores imbalance/momentum/target,
and simulates market fills at the first valid primary depth frame at or after the sampled order arrival.
It records decision, arrival and simulated fill timestamps separately. It never substitutes synthetic
liquidity for missing book levels; thin books can fill partially and missing/invalid depth or
an observation that is too late can leave an order unfilled. Unresolved orders at the end of a
recording are reported separately. Ending inventory is marked to the last observed bid, not force-closed;
that mark ignores the costs and available liquidity of an actual exit and can overstate realizable equity.

The single and rolling walk-forward CLIs embargo 60 seconds by default between training and test.
Use `--embargo-seconds` to set a gap suited to the research horizon; the temporal gap is not an
estimate of overfitting risk. Equal timestamps are kept together, and thin splits after the gap fail.
Training selection requires a closed position and ranks on realized net PnL with a drawdown penalty.
Rolling results distinguish positive mark-to-market windows from positive, flat-at-end windows with
at least one closed position and no pending order. Reserve a separate final holdout and do not tune
on these reports. Replay still does not share all production risk/sizing rules or model matching-engine
queue priority, and no new test result establishes a live trading edge.

## 2. SQLite batch writes

`PaperStore(async_writes=True)` buffers state/trades and flushes on a background thread (WAL + batch).
Call `flush()`/`close()` for durability on shutdown.

## 3. Feature time-series

`FeatureTimeSeriesStore` (`FEATURES_DB_PATH`) stores mid/spread/imbalance/score rows for fast range queries.
Raw L2 remains gzip JSONL; export features to ClickHouse/Parquet for multi-TB archives.

## 4. Market impact

`market_impact_bps(notional, visible_liquidity, coefficient)` — Almgren-style √participation.
Wired into `ExecutionSimulator` and L2 backtest. Tune `IMPACT_COEFFICIENT`.

## 5. API auth

Remote requests need `Authorization: Bearer <NEXORA_API_TOKEN>` **or** a JWT from
`app.auth.issue_token()` when `NEXORA_JWT_SECRET` is set. Optional `CORS_ORIGINS`.
