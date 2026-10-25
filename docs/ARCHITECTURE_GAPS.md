# Closed architecture gaps

## 1. L2 event-driven backtest
- Module: `app/l2_backtest.py`
- CLI: `python scripts/run_l2_backtest.py data/market-history.jsonl.gz`
- Replays MarketHistoryWriter gzip JSONL ms-by-ms; walks visible book + Almgren impact.

## 2. SQLite non-blocking path
- In-memory `RuntimeState` for hot reads
- `PaperStore` WAL + batch flush
- `AsyncIoQueue` (`app/io_queue.py`) enqueued from engine loop

## 3. Time-series scale path
- Capture: gzip JSONL L2
- Features: `FeatureTimeSeriesStore` (indexed SQLite)
- Export: `export_rows` / `export_jsonl` → ClickHouse / Timescale / Parquet offline

## 4. Market impact
- `market_impact_bps`: linear + sqrt participation
- `liquidity_based_slippage_bps`: book-level walk + impact

## 5. API hardening
- Bearer `NEXORA_API_TOKEN` or JWT (`NEXORA_JWT_SECRET`)
- CORS via `CORS_ORIGINS`
- Per-IP rate limit `NEXORA_RATE_LIMIT_PER_MIN` (default 120)
