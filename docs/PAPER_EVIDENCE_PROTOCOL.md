# Nexora Quant - Paper Evidence Protocol

This document defines a diagnostic paper-evidence standard. It is not a return
forecast and does not authorize live trading.

## 100 USDT profile

Use `.env.paper-100usdt.example` as a separate profile. It assumes Spot VIP0
fees at 0.10% per side, with BNB fee discount disabled, and explicitly models
paper slippage and latency. Verify the current account fee schedule before
comparing paper results to any live account.

## Minimum evidence window

Run continuously for 1-2 weeks where practical. Report the session window and
data gaps. Do not call a small or interrupted sample an edge.

A provisional pass requires all of the following:
- At least 50 fully closed, accounting-complete trades.
- Fee-net mean expectancy strictly greater than 0 USDT per closed trade.
- Observed peak-to-trough equity drawdown below 8% of peak equity.
- Daily fee spend does not exceed the configured 0.75 USDT budget.
- No unreported market-history drops, stale-book periods, or ledger gaps.
- Maker attempts, fills, timeouts, and markout coverage are reported; missing
  observations are not treated as zero-cost fills.

These are research acceptance thresholds, not guarantees. A pass is not proof
of future profitability. A fail or insufficient sample means continue paper
observation or disable entries; do not relax gates to manufacture a pass.

## Accounting definitions

- Closed trade PnL is the paper ledger's realized PnL after allocated entry fee
  and exit fee. Simulated slippage is reflected in the execution price.
- Session expectancy is the arithmetic mean of all complete closed-trade PnLs
  recorded since this process session began; recent-fill display limits must
  not truncate the sample.
- Max drawdown is the largest observed peak-to-subsequent-trough equity decline
  from sampled paper equity, both in USDT and percent of the peak.
- Daily fees are reset by UTC day in the runtime session counters.
- Trades/hour counts entry fills observed in the trailing 60 minutes.

## Known limitations

Runtime session counters are in-memory and reset on process restart; they are
not a durable multi-week evidence ledger yet. The paper trade ledger persists,
but a future P0 follow-up must rebuild session metrics from persisted trades
and equity snapshots before claiming restart-proof evidence. Maker metrics
remain zero/unknown unless the maker path is enabled and instrumented. No
markout-based edge claim is available until the 1s/5s/30s observations exist.
