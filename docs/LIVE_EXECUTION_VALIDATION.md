# Live-execution validation gates

This document records required evidence before any live-execution claim. It does not enable mainnet trading and is not evidence that these checks have passed.

## Current status

- [ ] Offline OCO fill reconciliation is complete and idempotent across every exchange history edge case.
- [ ] Binance Spot Testnet order lifecycle has passed end-to-end validation on the exchange.
- [ ] Net-of-fees profitability has been independently evaluated.
- [x] Implemented terminal OCO history discovery, child-order/trade retrieval, quantity reconciliation, trade-ID idempotency, and fail-closed handling for incomplete or unpriced commissions.
- [x] Added mocked recovery tests and an opt-in Testnet market/OCO-create/cancel/history smoke test; the live Testnet smoke test has not yet been run.
- [x] Unknown or inconsistent state fails closed rather than placing a speculative replacement order.
- [x] Default mode remains paper and the default Binance endpoint remains testnet.
- [x] Configuration now rejects mainnet live mode even when `LIVE_CONFIRM` is set; regression tests cover this fail-closed gate.

## 1. OCO reconciliation after downtime

The exchange-hosted OCO can execute while the process is offline. On restart, account balances alone are not sufficient to infer realized PnL, cost basis, fees, commission asset, or which OCO leg executed. Do not mark the local ledger reconciled based only on balances or the currently open-order list.

Implemented in this branch:

1. The REST client retrieves historical order lists, individual OCO list details, child orders, and trade fills.
2. Startup discovers bot-owned terminal OCO lists even if the last local snapshot missed the list ID, and reconciles them before overwriting the ledger with current account balances.
3. Child order executed quantities must match the sum of exchange trades. Exchange trade IDs and OCO list IDs are persisted as idempotency keys.
4. Actual quote/base commissions are accounted for; unpriced third-asset commissions, missing/truncated history, nonterminal child orders, and mismatches fail closed before accounting mutations.
5. Added unit tests cover a completed OCO fill, repeated recovery after snapshot restore, unpriced commission, and active OCO behavior.

**Remaining limitation:** mocked tests do not establish every exchange edge case. Stop-leg/TP-leg fills under real testnet conditions, partial-fill scenarios, and restart/timeout races still require exchange-side validation. The bot intentionally stays fail-closed on ambiguous history.

## 2. Binance Spot Testnet end-to-end validation

Unit tests and CI do not prove that signed requests, exchange filters, order-list responses, fills, commissions, reconnects, or cancellation behavior work against the exchange.

Run this only with a dedicated Binance Spot Testnet account and testnet-only credentials. Do not use mainnet credentials in CI. The test must refuse to run if the configured REST endpoint is not the Spot Testnet endpoint.

Acceptance matrix:

- [x] Added an opt-in smoke test that verifies testnet endpoint identity, public connectivity, signed account/balance, symbol filters, a small testnet market buy, OCO creation/cancel, and historical list lookup; it is gated by `NEXORA_RUN_SPOT_TESTNET_E2E=1`.
- [ ] Run the opt-in test with dedicated Spot Testnet credentials and capture its actual result.
- [ ] Verify both child-order states and reconcile every returned fill/trade against the local ledger.
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

Keep `TRADING_MODE=paper` for normal development. `app/config.py` now rejects `TRADING_MODE=live` with `BINANCE_TESTNET=false`, even if the confirmation string is present. This is an intentional fail-closed guard until reconciliation and Testnet gates have evidence and the profitability evaluation has been reviewed. Testnet live execution remains available for controlled testing; this does not mean its end-to-end run has occurred.
