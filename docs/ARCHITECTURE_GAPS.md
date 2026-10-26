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

## 6. Live OCO failure → emergency flatten
- `app/live_hardening.py` monkey-patches `LiveExecutor` at import (engine_setup).
- After every live BUY: `install_protection_or_flatten` → 3 OCO retries (~0.25s × attempt).
- On final failure: `emergency_flatten` (market sell) + `state.emergency` + kill switch.
- Contract tests: `tests/test_oco_emergency.py`.

## 7. IO queue depth monitoring
- `AsyncIoQueue.stats()` → `queue_depth`, `queue_peak`, `dropped_state`, `writes`.
- Engine loop samples every 50 ticks; warns when depth > 70% of maxsize.
- Trades never drop: full queue → synchronous `append_trade` fallback.
- Dashboard / snapshot exposes `io_queue_stats` for stress-test visibility.

## 8. SQLite WAL + concurrent dashboard reads
- Shared helper: `app/sqlite_util.configure_sqlite` / `connect_sqlite`
- `PaperStore` and `FeatureTimeSeriesStore` set `PRAGMA journal_mode=WAL`, `busy_timeout`, `synchronous=NORMAL`
- Writers (AsyncIoQueue worker) and readers (FastAPI snapshot) no longer rely on exclusive default journal locks

## 9. uvloop (optional performance)
- `pip install -e ".[perf]"` → `uvloop`
- `app/main.py` installs uvloop when present (Linux); falls back to asyncio
- Documented for Tokyo VPS deploy in `docs/AWS_TOKYO.md`

## 10. Time-driven UTC day rollover
- Event path still calls `risk.rollover_day` on ticks (`engine_tick`)
- Background task every 30s in `engine_loop` resets `realized_pnl_today` even if the book is silent at 00:00 UTC

## 11. History / multi-pair backpressure
- `MarketHistoryWriter(max_pending=N)` drops oldest pending records under burst
- Engine default `max_pending=4000`; `scripts/capture_multi_symbol.py` uses 8000 per symbol
- `AsyncIoQueue` already drops oldest **state** snapshots; trades sync-fallback when full
