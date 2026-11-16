# Roadmap

## Current engineering baseline

- Binance Spot depth streams with sequence-gap resync, per-symbol reconnect telemetry, and stale-symbol exclusion
- Paper ledger persistence and restart restoration; live exchange balance/OCO reconciliation before strategy startup
- Exchange-hosted OCO protection with stable client IDs, lookup after ambiguous HTTP responses, and cancellation verification before market exits
- Actual fill commission accounting; unpriced commission assets invalidate realized-PnL learning
- Online paper learner adapts only from fee-complete closed trades; mainnet learner remains frozen
- Conservative fee assumptions; BNB discount disabled unless explicitly configured and actually eligible
- L2 backtest marks equity at every valid depth event, includes visible-book execution, fees, impact, latency and partial-fill simulation
- Multi-asset rolling chronological OHLCV walk-forward runner: `scripts/evaluate_profitability.py`
- Mainnet gate requires recent paper evidence and a source-bound approval stamp
- Dashboard reports engine health, equity, drawdown, fees, position and learner telemetry

## Required evidence before mainnet consideration

1. Run the 48-hour paper evidence gate on the actual host and preserve its generated report.
2. Run the manual GitHub Spot Testnet E2E workflow with dedicated testnet-only API keys; confirm market fill, OCO create/query/cancel, and cleanup. This test is opt-in and is not executed by the normal unit suite.
3. Capture several assets across trend, range, choppy and stressed periods. Run rolling windows with costs and inspect worst windows, not only the mean.
4. Run a browser dashboard smoke test and verify its figures against SQLite and exchange fills.
5. Reconcile live account balances, fills, commissions and protective order lists on a dedicated low-value account before enabling strategy orders.

## Known limits (not closed by unit tests)

- Public L2 diffs do not reveal hidden liquidity, queue priority, all cancellations, or matching-engine ordering.
- OHLCV and L2 replay are not full exchange queue simulators; historical data quality and survivorship bias remain external risks.
- Paper learning is online adaptation, not a statistically proven reinforcement-learning system. It is not allowed to self-promote into mainnet.
- Spot Testnet behavior and symbol/filter availability can differ from mainnet. Testnet execution is not mainnet validation.
- The live executor remains single-symbol/single-position. Multi-asset live portfolio routing is intentionally disabled.
- No backtest, testnet run, or CI result proves future profitability or eliminates gaps, outages, or slippage.
