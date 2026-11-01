# Honest limits (retail Nexora Quant)

## What this bot is

- Binance **Spot** L2 microstructure bot (paper / small live).
- Alpha from **1–3s order-flow persistence**, not co-located HFT.
- OnlineLearner adapts gates from **closed trades** with anti-overfit guards.

## OnlineLearner vs backtest

| Mode | Weights |
|------|---------|
| L2 backtest | Strategy uses fixed config scores; does not mutate live learner mid-replay |
| Paper/live | Learner may adapt; freeze with `learner.freeze(True)` or `LEARNER_FROZEN=true` for parity runs |
| Anomaly trade | Outlier PnL is logged as skip — does not rewrite entry/size |

If live learner has adapted for a week, **replaying old JSONL with frozen base weights is the fair compare**. Claiming identical live vs backtest curves while weights move is invalid.

## Not in this repo (phase-2 infrastructure)

1. **Rust/C++ L2 ingester** — Python asyncio is the current path. Native ingest is a separate project (latency wins matter near the matching engine).
2. **ClickHouse / Redis OM** — SQLite + WAL + AsyncIoQueue is intentional for a single-node paper/small-live desk.
3. **Full Futures + funding alpha** — Spot only for now. Funding-as-filter can come later without perpetual margin risk.
4. **GARCH regime pack** — ATR + regime classifier approximate vol targeting without a full econometric stack.

## Dynamic risk (already in path)

- `app/atr_stops.py` — ATR / spread scaled TP-SL with fee-aware floors.
- `USE_ATR_TARGETS` / `VOL_TARGET_ENABLED` in settings when enabled.

## Go-live order

1. 48h+ paper, fee-net expectancy documented
2. Learner anomaly_skips / frozen parity checked
3. Testnet → small mainnet (withdrawals off)
4. Then Tokyo VPS — not before
