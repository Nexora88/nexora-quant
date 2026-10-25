# Research hardening (L2 backtest, storage, impact, auth)

## 1. L2 event-driven backtest

```python
from app.l2_backtest import L2BacktestConfig, run_l2_backtest, summarize_l2_result

result = run_l2_backtest("data/market-history.jsonl.gz", L2BacktestConfig(entry_min_score=0.5))
print(summarize_l2_result(result))
```

Replays `MarketHistoryWriter` gzip JSONL in timestamp order, scores imbalance/momentum/target,
walks visible book levels for fills, applies square-root impact. Not a full exchange matching engine.

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
