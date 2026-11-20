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

1. **Implemented for separate workers:** paper and live processes use distinct default SQLite ledgers, unique account identities and account-scoped learner state in the shared registry. Run both processes separately; they have independent executors and can consume the public market feed concurrently.
2. **Foundation added, evidence enrichment pending:** versioned paper-only strategy snapshots, parameter allowlist, evidence checks, operator-approved live assignment and rollback exist in `app/dual_account.py`. Add market-data fingerprint, training window, fee assumptions, symbol/regime coverage and independently reproducible validation artifacts.
3. Finish promotion validation against independently reproducible chronological out-of-sample artifacts; reject stale, incomplete, under-sampled or fee-negative candidates.
4. **Implemented:** each worker persists its own learner state. Live adaptation is driven only by exchange-confirmed FILLED closes with complete fee accounting; paper outcomes are never copied into the live learner. Hard risk controls are not learnable.
5. **Partially implemented:** live workers now reconcile free quote balance, total base balance and open OCO-list count with Binance every 30 seconds; mismatches and API failures activate the kill switch. Add full per-fill trade-history/commission reconciliation and coverage for non-OCO open orders.
6. Complete manual Spot Testnet E2E, rolling multi-asset/multi-regime OOS evidence, dashboard-to-ledger reconciliation and operator kill-switch drills.

## Mainnet evidence policy

Use docs/GO_LIVE_CHECKLIST.md as the single source of truth. The minimum paper window is 168 hours and at least 50 fee-complete closed trades, with positive fee-net expectancy, drawdown below 8%, daily fees no greater than 0.75 USDT, no data/ledger gaps, multiple OOS windows, successful Spot Testnet E2E, exchange reconciliation and an operator-reviewed kill switch. These are screening gates, not a return forecast or proof of safety.

## Known limits

- Public L2 does not reveal hidden liquidity, queue priority, all cancellations or matching-engine ordering.
- OHLCV and L2 replay are not full exchange queue simulators; historical data quality and survivorship bias remain external risks.
- The current OnlineLearner is bounded online adaptation, not proven reinforcement learning.
- Paper maker queue priority is not simulated.
- The live executor remains single-symbol/single-position.
- Continuous exchange/local-ledger reconciliation is not yet wired into the live executor. Spot Testnet E2E still requires dedicated credentials and an actual manual workflow run; CI's normal test suite skips it.
- No backtest, testnet run or CI result proves future profitability or eliminates gaps, outages or slippage.
