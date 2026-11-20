# Institutional Readiness Scorecard

This scorecard is a hard release checklist, not a marketing grade. Any red item blocks mainnet strategy orders.

| Gate | Required evidence | Current repository assessment |
|---|---|---|
| CI baseline | Full pytest, Ruff, compile, dependency/version consistency | CI workflow exists; exact branch must pass before merge |
| Live order lifecycle | Explicit state transitions, idempotent client IDs, timeout recovery, lost-response tests | Explicit PENDING/OPEN/PARTIALLY_FILLED/FILLED/CANCELLED/REJECTED/UNKNOWN state machine now tracks latest intent; timeout/chaos integration and exchange reconciliation still require CI + Testnet evidence |
| Exchange reconciliation | Free/locked balances, open orders/OCO, recent fills and commission assets vs ledger | Startup balance/OCO recovery exists; complete recurring account-vs-ledger reconciliation is not proven |
| Health/dead-man | Fresh depth, heartbeat, uncertain-order and risk gates; external watchdog | Health/alerts need end-to-end verification; external watchdog not evidenced |
| Risk | Daily/weekly loss, fees, portfolio heat, single-position live | Daily loss/fee and single-position constraints exist; weekly loss/portfolio heat not fully evidenced |
| Paper/live parity | Same accounting, partial fills, maker timeout and actual commissions | Fee-aware accounting exists; passive queue and full parity remain limited |
| Research promotion | Multi-asset/multi-regime OOS criteria and signed parameter approval | Source-bound GO_LIVE stamp exists; independent OOS parameter approval is not complete |
| Audit/DR | Append-only privileged-action audit, crash-mid-position restore | Snapshots and OCO recovery exist; immutable audit chain and chaos recovery remain incomplete |
| Evidence | 48h+ clean paper, fee-net positive expectancy, adequate closed trades | Must be collected on the actual deployment; cannot be inferred from unit tests |
| Spot Testnet | E2E order/OCO/reconcile/cleanup with dedicated credentials | Manual workflow exists; successful current run must be attached and reviewed |

## 20 USDT operational envelope (candidate, not approval)

config/live-20usdt.env.example is a conservative Testnet-first template:
- One configured execution symbol and one live position only; the scanner can watch multiple symbols but live multi-position routing remains disabled.
- 5 USDT target/max notional, leaving the rest uncommitted.
- 0.25 risk-per-trade sizing input (configuration is expressed in percentage points), 1 USDT daily loss ceiling, 0.15 USDT daily fee ceiling.
- VIP0 fee assumption; BNB discount off.
- No multi-position, automatic live symbol rotation, or learner promotion.

The exchange's current LOT_SIZE, MARKET_LOT_SIZE, MIN_NOTIONAL/NOTIONAL, and asset precision are authoritative. If the current symbol filters do not permit a 5 USDT order, do not increase the order cap automatically; choose another eligible symbol or keep live disabled. Fees, spread, slippage and partial fills can still make a small account uneconomic.

## Non-negotiable release sequence

1. CI green on the exact commit.
2. Dedicated Spot Testnet E2E green, including lost-response and OCO cleanup paths.
3. At least 48 hours of durable paper evidence with sufficient closed trades and positive fee-net expectancy.
4. Multi-asset, multi-regime walk-forward with minimum sample thresholds, worst-window drawdown and no-trade windows explicitly reported.
5. Source fingerprint and parameter approval artifacts valid for the exact deployed source.
6. Operator verifies exchange permissions (withdrawals disabled, IP allowlist), symbol filters, balances and kill-switch procedure.
7. Start with strategy orders disabled; operator explicitly enables the approved mainnet profile.

No scorecard can establish that the strategy will make money or prevent losses. The objective is controlled, measured exposure and fail-closed operation.


## Multi-symbol scanning versus live routing

The engine already discovers a USDT-major universe, starts synchronized depth streams for the watch list, maintains side-book snapshots, and ranks candidates. The current live executor is still bound to one configured symbol and one position. The paper engine also maintains one active position; its per-symbol research replays are independent bankroll runs, not a shared-cash multi-position portfolio. Do not interpret scan breadth as multi-position execution readiness.

A 20 USDT account may ultimately support two or three concurrent positions only if current exchange filters permit the minimum order sizes and the shared-wallet allocator reserves fees and cash. The candidate operational ceiling is three positions, not unlimited orders. Live remains hard-limited to one until per-symbol OCO, per-symbol ledgers, shared balance reservation, periodic account reconciliation, and restart recovery are covered by tests and Spot Testnet evidence.
