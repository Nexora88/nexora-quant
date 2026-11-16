# Scalp / micro-edge mode

## Goal
Frequent small wins that **beat round-trip fees**, not lottery 1.2% TPs.

## Defaults
- ATR band: SL ~0.15–0.32%, TP ~0.40–0.90% (regime scaled)
- Baseline: `TAKE_PROFIT_PCT=0.55`, `STOP_LOSS_PCT=0.18`
- Use the verified account fee tier; keep BNB discounts disabled unless the account actually pays fees in BNB.
- `WICK_STOP_CONFIRMATIONS=2`
- Entry alpha is estimated from the same dynamic TP used by the exit manager; TP floor includes at least 2.0× estimated round-trip friction (fees + spread + simulated slippage + impact).
- Momentum is measured on elapsed 1m and 5m windows, not just the last N websocket events. Spot entries are blocked against confirmed negative momentum; losing positions can exit on a confirmed multi-timeframe reversal.
- Scalp time discipline: 20s soft-exit minimum and 900s maximum hold; hard risk exits are never delayed.

## Stack
- SQLite WAL, OnlineLearner observe/record, order-flow 1–3s, BTC alt lock, max concurrent=1

## Honest limits
Spot without BNB can erase a 0.4% TP. Tokyo cuts RTT; it does not invent edge.
