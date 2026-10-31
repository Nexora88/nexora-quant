# Scalp / micro-edge mode

## Goal
Frequent small wins that **beat round-trip fees**, not lottery 1.2% TPs.

## Defaults
- ATR band: SL ~0.15–0.32%, TP ~0.40–0.90% (regime scaled)
- Baseline `.env`: `TAKE_PROFIT_PCT=0.55`, `STOP_LOSS_PCT=0.18`
- `FEE_USE_BNB_DISCOUNT=true` (pay fees in BNB on Binance)
- `WICK_STOP_CONFIRMATIONS=2` — single liquidation wick does not force SL
- Entry blocked if planned TP < round-trip fee × `MIN_EDGE_OVER_FEES` (1.5)

## Already in stack
- SQLite **WAL** — not Redis; adequate for retail desk
- OnlineLearner observe while flat + record on exit
- Order-flow 1–3s accumulation
- BTC correlation lock for alts
- Portfolio max concurrent = 1

## Honest limits
- Spot without BNB can erase a 0.4% TP
- HFT co-lo is not the model; sustained flow is
- AWS Tokyo cuts RTT; it does not invent edge

## Deploy
See `docs/GO_LIVE_CHECKLIST.md`. Prefer `asia-northeast1` + Docker.
