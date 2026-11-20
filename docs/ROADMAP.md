# Roadmap

## Current engineering baseline

- Binance Spot depth streams with sequence-gap resync, per-symbol reconnect telemetry, and stale-symbol exclusion.
- Paper ledger persistence and restart restoration; live exchange balance/OCO reconciliation before strategy startup.
- Exchange-hosted OCO protection with stable client IDs, lookup after ambiguous HTTP responses, and cancellation verification before market exits.
- Actual fill commission accounting; unpriced commission assets invalidate realized-PnL learning.
- Online paper learner adapts only from fee-complete closed trades. The 20 USDT paper example profile now enables this bounded learner by default.
- Conservative fee assumptions; BNB discount disabled unless explicitly configured and actually eligible.
- L2 backtest marks equity at every valid depth event, includes visible-book execution, fees, impact, latency and partial-fill simulation.
- Multi-asset rolling chronological OHLCV walk-forward runner: scripts/evaluate_profitability.py.
- Mainnet approval script now requires an operator scorecard in addition to a fresh overnight pass log; it checks paper duration/trade count, fee-net expectancy, drawdown, fee budget, data/ledger gaps, OOS windows, Spot Testnet E2E, reconciliation and kill-switch review.
- Dashboard reports engine health, equity, drawdown, fees, position and learner telemetry.

## Explicit target account model

- One paper account with a 20 USDT virtual bankroll and one separate 20 USDT exchange account for live use.
- Each account must keep its own balance, positions, fills, fees, PnL, risk state, persistent ledger and learner history.
- Shared knowledge means versioned strategy candidates and validated parameters only; it never means sharing funds, positions, orders or PnL.
- Paper candidates must pass chronological out-of-sample validation and explicit promotion review before live adoption.
- Live hard risk controls are immutable to either learner. No model may raise order caps, daily loss limits or disable stops/kill switches.

## Required engineering before claiming the dual-account learning pipeline is complete

1. Implement isolated account-scoped persistence and learner state for simultaneous paper and live processes.
2. Implement versioned candidate snapshots with provenance, market-data fingerprint, training window, fee assumptions, closed-trade count, regime/symbol coverage, metrics and deterministic rollback.
3. Implement promotion validation against independent out-of-sample windows; reject stale, incomplete, under-sampled or fee-negative candidates.
4. Add a live outcome learner that records only exchange-confirmed, fee-complete closed trades, isolated from paper state and incapable of modifying hard risk controls.
5. Implement recurring exchange/local-ledger reconciliation and fail-closed handling for balance, commission, open-order and fill discrepancies.
6. Complete manual Spot Testnet E2E, rolling multi-asset/multi-regime OOS evidence, dashboard-to-ledger reconciliation and operator kill-switch drills.

## Mainnet evidence policy

Use docs/GO_LIVE_CHECKLIST.md as the single source of truth. The minimum paper window is 168 hours and at least 50 fee-complete closed trades, with positive fee-net expectancy, drawdown below 8%, daily fees no greater than 0.75 USDT, no data/ledger gaps, multiple OOS windows, successful Spot Testnet E2E, exchange reconciliation and an operator-reviewed kill switch. These are screening gates, not a return forecast or proof of safety.

## Known limits

- Public L2 does not reveal hidden liquidity, queue priority, all cancellations or matching-engine ordering.
- OHLCV and L2 replay are not full exchange queue simulators; historical data quality and survivorship bias remain external risks.
- The current OnlineLearner is bounded online adaptation, not proven reinforcement learning.
- Paper maker queue priority is not simulated.
- The live executor remains single-symbol/single-position.
- The isolated dual-account shared-knowledge pipeline is not yet implemented end-to-end.
- No backtest, testnet run or CI result proves future profitability or eliminates gaps, outages or slippage.
