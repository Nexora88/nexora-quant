# Go-Live Checklist (paper → Spot Testnet → mainnet)

## 0. Account and learning boundaries

- Exactly one 20 USDT paper account and one separate 20 USDT live account.
- The paper account uses public real-time market data and simulated execution/fees. Its balance, positions, fills, fees, PnL, SQLite state and learner history are paper-only.
- The live account has its own exchange balance, orders, fills, fees, PnL, risk state and learner history. Paper cash or PnL must never be copied into the live ledger.
- Paper-learned parameters are research candidates, not live instructions. They may be considered for live only after reproducible out-of-sample validation and operator approval. Direct automatic paper-to-mainnet promotion is prohibited.
- Live hard risk limits (order cap, daily loss, fee cap, stop protection, stale-data checks and kill switch) are not learnable and must never be relaxed by the learner.
- OnlineLearner is bounded online adaptation from completed fee-accounted trades, not a statistically proven reinforcement-learning system.

## 1. Paper account: 20 USDT

Copy .env.paper.example to a paper-specific env file. It configures one 20 USDT bankroll, one open position, fee-aware simulated fills and an unfrozen paper learner. Run this process on port 8000. Copy .env.live.example to a separate live-process env file; it defaults to Spot Testnet, uses a separate live SQLite ledger, a separate account learner and port 8001. Both processes may share only DUAL_ACCOUNT_DB_PATH for strategy metadata. Never point LIVE_DB_PATH and PAPER_DB_PATH at the same file. The learner changes bounded strategy preferences only after completed trade outcomes; repeated market ticks are not independent training labels.

Run the paper and live/Testnet services as separate processes with their respective env files and retain their databases. Do not reset either database to make evidence look better. The live profile is deliberately Testnet-only by default; it is not a mainnet authorization.

    uvicorn app.api:app --host 127.0.0.1 --port 8000
    # after the evidence window:
    PYTHONPATH=. python scripts/overnight_paper_check.py

Minimum paper evidence for mainnet consideration is 168 continuous hours, at least 1,000 primary depth ticks, at least 50 fee-complete closed trades, and positive fee-net expectancy. The operator scorecard must additionally attest to drawdown below 8%, daily fees no greater than 0.75 USDT, zero unreported data/ledger gaps, multi-window out-of-sample results, Spot Testnet E2E success, exchange reconciliation and kill-switch review. These are minimum review gates, not a guarantee of future returns.

To export a measured paper learner snapshot, prepare a scorecard from retained evidence and run `PYTHONPATH=. python scripts/strategy_registry.py publish --evidence-json /path/to/oos-scorecard.json`. Review the candidate, then explicitly promote it with `PYTHONPATH=. python scripts/strategy_registry.py promote --version STRATEGY_VERSION --i-approve-live-strategy`. The live process loads only the assigned version on startup. Roll back with `PYTHONPATH=. python scripts/strategy_registry.py rollback`. Candidate parameters are limited to entry threshold, size bias, TP scale and compounding preference; hard risk limits cannot be transferred. Live learning remains separate and records only exchange-confirmed, fee-complete closes.

## 2. Spot Testnet before any mainnet

Use dedicated Spot Testnet credentials only. Keep withdrawals disabled. Run the manual .github/workflows/spot-testnet-e2e.yml workflow and verify:
- market order/fill handling;
- OCO create, query, cancel and protection recovery;
- ambiguous HTTP response / client-order-ID lookup;
- no residual position or open OCO list after cleanup.

A unit test or successful CI run is not a substitute for the live exchange Testnet workflow. Testnet is not mainnet validation.

## 3. Mainnet scorecard and fail-closed gate

Create an operator-reviewed JSON scorecard from retained paper, OOS, Testnet and reconciliation artifacts. Do not guess or fabricate values.

Example schema only (these values are NOT evidence that the repository has passed):

    {
      "paper_hours": 168,
      "closed_trades": 50,
      "fee_net_expectancy_usdt": 0.01,
      "max_drawdown_pct": 7.9,
      "max_daily_fees_usdt": 0.75,
      "data_gaps": 0,
      "ledger_gaps": 0,
      "oos_windows": 4,
      "positive_oos_windows": 3,
      "testnet_e2e_pass": true,
      "exchange_reconciled": true,
      "kill_switch_reviewed": true
    }

Use measured values and preserve the underlying reports. The gate checks at least 168h, 50 closed trades, positive fee-net expectancy, drawdown below 8%, daily fees <=0.75 USDT, zero gaps, at least four chronological OOS windows (three positive), successful Spot Testnet E2E, exchange reconciliation and operator-reviewed kill switch.

    PYTHONPATH=. python scripts/go_live_gate.py \
      --i-understand-real-money \
      --overnight-log /path/to/overnight_out.txt \
      --evidence-json /path/to/operator-reviewed-scorecard.json

The gate removes any prior approval stamp before checking and does not change trading mode or submit orders. It writes a source-fingerprinted approval only when all checks pass. A passing gate is not a profitability guarantee. The final mainnet switch still requires the operator's explicit decision and a separately reviewed 20 USDT configuration.

## 4. 20 USDT live-account constraints

- Keep one symbol and one open position only.
- Use exchange-reported free balance and symbol filters; never force a trade to satisfy minimum notional.
- Keep API withdrawals disabled and restrict keys by IP.
- Use a conservative order cap, daily loss cap and fee cap appropriate to 20 USDT. The existing 20 USDT candidate profile is not a claim that all symbols can trade at its minimum notional.
- Startup exchange reconciliation and OCO protection must fail closed. Any balance, fill, commission, open-order or local-ledger mismatch blocks new entries.
- Live outcome learning must be account-scoped and accept only exchange-confirmed, fee-complete closed trades. The new storage primitives support this isolation, but engine integration is still pending. Neither learner may mutate hard risk limits.

## 5. Known limitations (must not be represented as closed)

- Paper does not simulate a true maker queue or queue priority; paper maker results cannot be treated as measured live maker performance.
- Public L2 does not expose hidden liquidity or matching-engine ordering.
- Historical replay is not a complete exchange simulator.
- The live executor remains single-symbol/single-position.
- Paper and live are now intended to run as separate engine processes with distinct default SQLite ledgers and account-scoped learner state; `app/dual_account.py` provides the shared strategy registry, explicit candidate promotion/rollback and a periodic reconciliation monitor primitive. The live close hook records only exchange-confirmed, fee-complete outcomes. The reconciliation monitor is not yet connected to the live executor's recurring exchange snapshot adapter, so continuous exchange/local reconciliation remains unfinished.
- The 20 USDT live account has not been proven profitable or safe merely by configuration. Testnet and real account reconciliation remain mandatory.

## 6. Data retention

Keep the paper SQLite database, market-history captures, overnight reports, OOS reports, Testnet artifacts and operator scorecard together. Snapshot before host migration. Never copy paper account rows into a live ledger.
