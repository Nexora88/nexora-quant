# Profit path (honest) — validation before compounding

**No guarantee.** This is an operating protocol, not a promise of returns.

## Reality check

- Spot VIP0 taker fees are approximately 10 bps per side before any account-specific discount; spread, impact and slippage are additional.
- A small take-profit target can be consumed by transaction friction. A signal is not a forecast.
- A 100 USDT account has high variance; growth requires repeated positive net expectancy after all costs, not a lucky session.

## Protocol (paper first)

1. Preserve the existing paper ledger. If a clean experiment is needed, back it up and use a separate paper database; never delete an open position or its accounting history.
2. Run strict paper for at least 48 hours with PAPER_SOFT_GATES=false and at least 20 fee-complete closed trades. If no valid signals occur, extend the observation period rather than weakening gates.
3. Require positive realized net expectancy after actual fees, controlled drawdown, complete commission accounting, and acceptable maker timeout/fill statistics.
4. If rolling fee-net expectancy is negative, halt new entries or run a separately labeled reduced-risk research cohort; do not disguise losses with soft gates.
5. Then run Spot Testnet E2E, review the fresh GO_LIVE gate, and obtain explicit operator approval before any mainnet experiment.

## Conservative 100 USDT research settings

| Knob | Initial setting | Purpose |
|------|-----------------|---------|
| MIN_EDGE_OVER_FEES | 2.0 | Estimated gross move must cover at least 2x all-in round-trip friction |
| RISK_PER_TRADE_PCT | 0.35 | Initial risk budget per trade, before stress slippage |
| MAX_DAILY_LOSS_USDT | 2.0 | Daily stop for the 100 USDT example account |
| MAX_DAILY_FEE_USDT | 0.75 | Fee churn ceiling |
| MAX_TRADES_PER_HOUR | 8 | Prevent overtrading |
| MAX_HOLD_SECONDS | 900 | Keep the position horizon consistent with scalping |
| MIN_HOLD_SECONDS | 20 | Avoid micro-churn; protective exits remain active |
| COMPOUND_FRACTION | 0.50 | Conservative sizing allocation; not a promise to reinvest profit |
| MAX_CONCURRENT_POSITIONS | 1 | Keep exposure and accounting simple |
| PAPER_SOFT_GATES | false | Validate the actual strict entry policy |

Use BNB discounts only if the Binance account is eligible and actually pays fees in BNB. Maker orders can fail to fill and may suffer adverse selection; never assume every fill is maker.

## Futures

Futures are not enabled by the current Spot executor. They require a separate adapter, margin and funding-cost model, mark-price/liquidation controls, reduce-only exits and independent testnet validation. Do not route Futures orders through the Spot client.

## Success definition

First milestone: durable positive fee-net expectancy with controlled drawdown in Spot paper. Second: repeat the evidence on Spot Testnet. Only after that should a tiny mainnet pilot even be considered. Faster compounding does not create an edge; it magnifies both gains and losses.
