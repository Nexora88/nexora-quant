# Scalp / micro-edge mode

## Goal
Frequent small wins that **beat round-trip fees**, not lottery 1.2% TPs.

## Defaults
- ATR band: SL ~0.15–0.32%, TP ~0.40–0.90% (regime scaled)
- Baseline: `TAKE_PROFIT_PCT=0.55`, `STOP_LOSS_PCT=0.18`
- `FEE_USE_BNB_DISCOUNT=true`
- `WICK_STOP_CONFIRMATIONS=2`
- Entry blocked if planned TP < round-trip fee × `MIN_EDGE_OVER_FEES` (1.5)

## Stack
- SQLite WAL, OnlineLearner observe/record, order-flow 1–3s, BTC alt lock, max concurrent=1

## Honest limits
Spot without BNB can erase a 0.4% TP. Tokyo cuts RTT; it does not invent edge.
