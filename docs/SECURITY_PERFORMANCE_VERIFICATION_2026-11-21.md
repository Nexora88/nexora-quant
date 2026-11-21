# Nexora Quant — Security & Performance Verification Report

**Assessment date:** 2026-11-21  
**Reviewed revision:** 44cd4a032e589dde5cb2ff686649a0dbc0a94622  
**Scope:** repository-level automated checks on the connected Windows development machine and GitHub Actions CI.

## Executive result

The repository's automated regression and consistency gates passed. This is an internal engineering verification report, **not** a third-party penetration test, independent code certification, or proof of profitable trading.

| Control | Result | Evidence |
|---|---|---|
| Full automated test suite | PASS | 409 passed, 1 skipped, 1 warning |
| Ruff static lint | PASS | ruff check . |
| Python bytecode compilation | PASS | compileall -q app scripts tests |
| Installed dependency consistency | PASS | pip check — no broken requirements |
| GitHub Actions CI | PASS | Run #901 |
| Mainnet live approval gate | PASS (negative/positive tests) | explicit confirmation + source-bound, expiring approval stamp |
| Testnet/Mainnet data isolation | PASS | separate default SQLite paths and account-learning IDs |
| Testnet order-size guard | PASS (code-level) | E2E runner/test restricts the order to 20 USDT |
| Credentialed Spot Testnet order/OCO E2E | NOT RUN | local Testnet API key and secret are absent |
| Bandit / pip-audit | NOT RUN | neither scanner is installed in the local environment |
| External penetration test | NOT RUN | no independent security firm assessment was performed |

## Reconciliation controls added

- Startup performs a full symbol order-history and fill-history audit before live execution is allowed.
- Every new live fill is committed synchronously to the live SQLite ledger using an exchange-order-based idempotency key, including when later tick processing raises an exception.
- The recurring monitor checks balances, active ordinary orders, OCO lists and child order IDs; full order/fill history is refreshed periodically.
- Exchange fills without matching local order records, local order IDs absent from exchange history, unmanaged open orders, unpriced commissions and per-asset commission deltas are hard mismatches.
- Historical third-asset commissions use the local execution-time per-asset valuation. The audit does not substitute today's ticker price for a historical conversion.
- Testnet and Mainnet use separate local execution databases and separate account-learning identities by default.

## Performance evidence and limits

The full regression suite completed in **33.64 seconds** on the connected Windows machine. The slowest listed individual tests were approximately 2.4 seconds. This measures test-suite runtime, not live order latency, market-data throughput, maximum sustainable symbols, or exchange API performance.

A real exchange performance benchmark cannot be claimed until authenticated Spot Testnet orders and streaming are exercised. No Mainnet order was submitted.

## 20 USDT launch profile

The repository's 20 USDT candidate profile is constrained to:
- 5 USDT maximum order notional (25% of the 20 USDT starting balance);
- one concurrent position;
- 0.25% configured risk per trade;
- 1 USDT daily loss cap and 0.15 USDT daily fee cap;
- Mainnet remains behind explicit operator confirmation and the source-bound go-live gate.

The active local .env remains in PAPER mode. This candidate profile is not activated by this report.

## Testnet execution blocker

The local .env.testnet has BINANCE_TESTNET=true and a 20 USDT order amount, but no dedicated Testnet API key/secret. The E2E runner stopped before submitting an order. Add dedicated Spot Testnet credentials locally (withdrawal permission disabled), then run:

    .\scripts\run_spot_testnet_e2e.ps1

Do not use Mainnet credentials in this file.

## Score-threshold decision

The active local entry threshold remains **0.45**. The existing rolling walk-forward evidence recorded no-trade fallback in its unseen windows for BTC/ETH/SOL; that sample cannot identify an optimal lower threshold. Reducing the threshold without a valid out-of-sample trade sample would increase activity without evidence of better net expectancy. A threshold sweep must be run on sufficiently rich chronological data and judged after fees, spread, slippage, drawdown and minimum trade-count requirements.

## Final disposition

**Automated repository quality gates: PASS.**  
**Authenticated Spot Testnet E2E: BLOCKED pending dedicated Testnet credentials.**  
**Independent external security certification and live performance proof: NOT ESTABLISHED.**  
**Mainnet real-money trading: NOT APPROVED by this report.**
