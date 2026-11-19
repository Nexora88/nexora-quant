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
- Daily fees are reset by UTC day. The central RiskManager blocks new entries once
  actual reported fill fees reach MAX_DAILY_FEE_USDT; exits remain permitted.
- Trades/hour counts entry fills observed in the trailing 60 minutes.
- 1s/5s/30s markout is signed mid-price movement in bps from fill price to the
  first observed book mid at or after each horizon. It is an execution diagnostic,
  not realized PnL and not a fill simulation.
- Maker attempt/fill/timeout counters increment only when the live LIMIT_MAKER
  path is actually invoked. A paper run with no maker route reports no sample.

## Known limitations

Session evidence counters and pending markout observations are now included in
the durable paper_state snapshot and restored at startup. This is checkpoint
persistence, not a full forensic rebuild from the append-only paper_trades table;
a missing/corrupt state checkpoint still requires manual reconciliation. Daily
fee blocking is enforced in the central entry gate. Maker metrics remain
unknown until real maker attempts occur; they are not inferred from taker fills.
Markout samples are sparse when book updates are sparse and must be reported
with their sample count and observation delay. The risk book groups current
equity, peak, drawdown, session PnL, daily realized PnL/fees, consecutive losses,
kill, emergency, and target-equity halt state; live risk policy remains disabled
for this paper profile.
