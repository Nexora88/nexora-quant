# Market support and staged rollout

## Current execution boundary

- Binance Spot: existing paper/live executor and Spot depth sequencing are present.
- Binance USDⓈ-M Futures: isolated cost, funding, sizing and liquidation-buffer primitives exist in app/futures_risk.py, but no production Futures order/position adapter is present yet. Do not route Futures orders through the Spot executor.
- The engine remains stopped unless the operator explicitly starts it. Current strategy work is paper-only.

## Shared strategy policy

1. Estimate round-trip commissions, spread, both-side impact/slippage and latency.
2. Reject a candidate unless estimated gross movement is at least 2.0x total estimated friction.
3. Require positive net edge and aligned signal evidence; no edge means no trade.
4. Use ATR-aware exits, one concurrent position, a 0.35% initial per-trade risk budget, 2 USDT daily loss cap for the 100 USDT example account, four-loss circuit limit, and 8 entries/hour.
5. Compound only through the capped sizing policy. The example deploy fraction is 0.50, not 100% of the account.
6. Paper soft gates are disabled by default. They cannot bypass the 2.0x cost-multiple rule.

The 2.0x threshold is a conservative research starting point, not a profit guarantee. The alpha estimate is heuristic and must be validated out of sample.

## Futures implementation gate

The first isolated Futures risk primitives now exist in `app/futures_risk.py`: conservative funding-cost estimation, stop-risk/margin-capped sizing (1x default), and fail-closed liquidation-buffer checks. They are unit-tested but are **not yet connected to an order executor**.

Futures must remain a separate adapter and separate account-risk ledger. Before enabling even testnet orders, implement and test:

- USDⓈ-M Futures REST signing, exchange filters, precision and minimum notional
- Futures market data and mark-price streams (not Spot depth sequencing)
- One-way position mode initially; explicit positionSide handling if hedge mode is ever added
- Isolated margin only; leverage capped at 1x during initial testnet validation
- Entry and exit fee schedule, funding-rate cost over expected holding time, spread, impact and adverse slippage
- Exchange-confirmed position reconciliation, reduce-only exits, protective stop verification, liquidation-distance checks
- User-data stream reconnect/reconciliation, idempotent client order IDs and a durable Futures kill switch
- Independent Futures paper simulation, testnet E2E, failure injection and walk-forward validation

No Futures mainnet order path should be enabled until every gate above is implemented and independently tested. Spot and Futures must never share a position ledger or silently share risk limits.

## Validation

- Run the full unit suite and static checks after strategy changes.
- Run strict Spot paper for at least 48 hours and require at least 20 fee-complete closed trades, positive net expectancy after actual fees, and controlled drawdown.
- Testnet validation comes after paper evidence. Mainnet remains blocked by the existing fresh source-fingerprint GO_LIVE approval gate.
