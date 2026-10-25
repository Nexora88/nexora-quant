# Live-execution validation gates

This document records required evidence before any live-execution claim. It does not enable mainnet trading and is not evidence that these checks have passed.

## Current status

- [ ] Offline OCO fill reconciliation is complete and idempotent.
- [ ] Binance Spot Testnet order lifecycle has passed end-to-end validation.
- [ ] Net-of-fees profitability has been independently evaluated.
- [x] Unknown or inconsistent state fails closed rather than placing a speculative replacement order.
- [x] Default mode remains paper and the default Binance endpoint remains testnet.

## 1. OCO reconciliation after downtime

The exchange-hosted OCO can execute while the process is offline. On restart, account balances alone are not sufficient to infer realized PnL, cost basis, fees, commission asset, or which OCO leg executed. Do not mark the local ledger reconciled based only on balances or the currently open-order list.

Required implementation and tests:

1. Persist the OCO list ID and client order IDs before relying on the protection.
2. On startup, query the exchange for the historical order-list state and both child-order states, including terminal states; query fills/trades for each child order.
3. Rebuild each fill from exchange trade IDs, executed quantity, quote quantity, price and commission asset/amount. Deduplicate using stable exchange trade IDs so repeated reconciliation is idempotent.
4. Apply partial fills and fees to the local position/ledger exactly once. Reconcile free and locked balances after applying fills.
5. If the exchange history is unavailable, incomplete, contradictory, or cannot be matched to the persisted position, keep order placement disabled and surface a clear manual-reconciliation state. Never guess the cost basis or automatically submit a replacement sell.
6. Test stop-leg execution, take-profit execution, partial fills where supported, cancel/replace races, app downtime, duplicate responses, API timeout, and repeated restart.

**Known limitation:** this checklist is not implemented merely by the existing fail-closed startup guard. Full offline OCO accounting remains incomplete until the above behavior is implemented and covered by tests.

## 2. Binance Spot Testnet end-to-end validation

Unit tests and CI do not prove that signed requests, exchange filters, order-list responses, fills, commissions, reconnects, or cancellation behavior work against the exchange.

Run this only with a dedicated Binance Spot Testnet account and testnet-only credentials. Do not use mainnet credentials in CI. The test must refuse to run if the configured REST endpoint is not the Spot Testnet endpoint.

Acceptance matrix:

- [ ] Public connectivity, server time and exchange-info/filter parsing.
- [ ] Signed account/balance request and insufficient/invalid request handling.
- [ ] Small testnet market order; assert terminal order state and reconcile every returned fill/trade.
- [ ] Exchange-hosted OCO creation; verify list ID, both child orders, and open-order-list state.
- [ ] Exercise both OCO outcomes in isolated testnet scenarios where the exchange permits; verify child states, trade IDs, commissions, balances and local ledger.
- [ ] Simulate network timeout after submission and reconnect; resolve by client order ID without submitting a duplicate.
- [ ] Restart with open OCO, completed OCO, and ambiguous exchange history; ambiguous cases must fail closed.
- [ ] Cancel/reconcile behavior, partial fills where reproducible, and repeated reconciliation idempotency.
- [ ] Save sanitized logs, timestamps, testnet endpoint identity, and assertions as a CI artifact. Never log API secrets or signed request URLs.

These checks require explicit testnet credentials and exchange-side setup. They are not considered passed until executed against Binance Spot Testnet; a mocked client is not an end-to-end substitute.

## 3. Profitability validation

No profit guarantee or production-readiness claim is permitted from unit tests, CI, a single backtest, or a successful testnet order.

Minimum research protocol:

- Use chronological rolling walk-forward windows across multiple assets and distinct market regimes. Keep final holdout periods out of parameter tuning.
- Include realistic fees, spread, adverse slippage, latency, partial/unfilled orders, market impact assumptions, and missing/disconnected data scenarios.
- Report net-of-cost expectancy, drawdown, tail losses, turnover, profit factor, sample size, and dispersion across windows/assets. Compare against simple baselines.
- Record all parameter choices before evaluation; include negative results and uncertainty. Do not infer future returns from simulated/testnet execution.
- Treat testnet as an order-lifecycle check, not proof of live-market profitability.

## Safety policy

Keep `TRADING_MODE=paper` for normal development. Do not enable mainnet real-money execution as part of this validation work. Mainnet must remain a separate, explicit operator decision after reconciliation and testnet gates have evidence; this project currently has not established those prerequisites.
