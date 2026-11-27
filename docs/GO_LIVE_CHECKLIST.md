# Go-Live Checklist (paper → Spot Testnet → mainnet)

## 0. Account and learning boundaries

- Exactly one 20 USDT paper account and one separate 20 USDT live account.
- The paper account uses public real-time market data and simulated execution/fees. Its balance, positions, fills, fees, PnL, SQLite state and learner history are paper-only.
- The live account has its own exchange balance, orders, fills, fees, PnL, risk state and learner history. Paper cash or PnL must never be copied into the live ledger.
- Paper-learned parameters are research candidates, not live instructions. They may be considered for live only after reproducible out-of-sample validation and operator approval. Direct automatic paper-to-mainnet promotion is prohibited.
- Live hard risk limits (order cap, daily loss, fee cap, stop protection, stale-data checks and kill switch) are not learnable and must never be relaxed by the learner.
- OnlineLearner is bounded online adaptation from completed fee-accounted trades, not a statistically proven reinforcement-learning system.

## 1. Paper account: 20 USDT

Copy .env.paper.example to a paper-specific env file. It configures one 20 USDT bankroll, one open position, fee-aware simulated fills and an unfrozen paper learner. Run this process on port 8000. Copy .env.live.example to a separate live-process env file; it defaults to Spot Testnet, uses a separate live SQLite ledger, a distinct `live-testnet` account identity, a frozen Testnet learner and port 8001. For a separately approved mainnet deployment, use a distinct `live-main` account identity and explicitly configure its learner only after all gates pass. Both processes may share only DUAL_ACCOUNT_DB_PATH for strategy metadata. Never point LIVE_DB_PATH and PAPER_DB_PATH at the same file. The learner changes bounded strategy preferences only after completed trade outcomes; repeated market ticks are not independent training labels.

Run the paper and live/Testnet services as separate processes with their respective env files and retain their databases. Do not reset either database to make evidence look better. The live profile is deliberately Testnet-only by default; it is not a mainnet authorization.

    uvicorn app.api:app --host 127.0.0.1 --port 8000
    # after the evidence window:
    PYTHONPATH=. python scripts/overnight_paper_check.py

Minimum paper evidence for mainnet consideration is 168 continuous hours, at least 1,000 primary depth ticks, at least 50 fee-complete closed trades, and positive fee-net expectancy. The operator scorecard must additionally attest to drawdown below 8%, daily fees no greater than 0.75 USDT, zero unreported data/ledger gaps, multi-window out-of-sample results, Spot Testnet E2E success, exchange reconciliation and kill-switch review. These are minimum review gates, not a guarantee of future returns.

To export a measured paper learner snapshot, prepare a scorecard from retained evidence and run `PYTHONPATH=. python scripts/strategy_registry.py publish --evidence-json /path/to/oos-scorecard.json`. Review the candidate, then explicitly promote it with `PYTHONPATH=. python scripts/strategy_registry.py promote --live-account live-testnet --version STRATEGY_VERSION --i-approve-live-strategy` for Testnet. Mainnet promotion must target `--live-account live-main` only after the full go-live gate and separate operator approval. The live process loads only the assigned version on startup. Roll back with `PYTHONPATH=. python scripts/strategy_registry.py rollback`. Candidate parameters are limited to entry threshold, size bias, TP scale and compounding preference; hard risk limits cannot be transferred. Live learning remains separate and records only exchange-confirmed, fee-complete closes.

## 2. Spot Testnet before any mainnet

Add the dedicated simulated-fund credentials as GitHub Actions secrets `BINANCE_SPOT_TESTNET_API_KEY` and `BINANCE_SPOT_TESTNET_API_SECRET`. Use an isolated Spot Testnet account with at least 20 USDT plus a fee buffer, no tradable BTC, and no open BTCUSDT orders or open order lists. Do not enter Mainnet credentials or paste secrets into a PR or log.

Run the manual `.github/workflows/spot-testnet-e2e.yml` workflow. It uses a fixed 20 USDT BTCUSDT buy and runs the production executor through SQLite order journaling, OCO creation, executor restart from the saved account, confirmed OCO cancellation, and a fee-accounted exit. The workflow checks for outstanding orders and tradable position residue. Download and retain `testnet-e2e-results.xml` from the successful workflow. A skipped lifecycle does not pass. Lost-response and delayed-visibility faults are covered by offline tests; a normal signed workflow run does not reproduce a network outage.

An unresolved OCO submission blocks additional orders, including an emergency market exit. Check the same list client ID on the exchange, then verify both child orders and fills before recovery. A single “order not found” response is not proof that the submission failed. Keep the SQLite database and do not manually reset the journal to force a retry. If upgrading an older deployment with a saved OCO client ID but no exchange match, reconcile it with the exchange before resuming.

A unit test or successful CI run is not a substitute for the signed Spot Testnet workflow. Testnet does not validate Mainnet execution quality or profitability.

The live engine uses public depth snapshots, depth streams, trades and candles from the same network as its order client. Testnet uses the [official Spot Testnet endpoints](https://developers.binance.com/en/docs/products/spot/testnet/web-socket-streams); it neither falls back to Mainnet market data nor runs the Mainnet auto-universe screen. The bounded signed workflow tests the executor, not automatic strategy entry.

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

Use measured values and preserve the underlying reports. The gate cross-checks the overnight run's duration, tick count, reconnects and closed-trade totals against minimum thresholds. For OOS evidence it reopens the absolute archive and manifest paths recorded in the report, recalculates the archive SHA-256, and rechecks the manifest source, coverage and symbol before issuing an approval. It checks for at least four chronological, non-overlapping OOS windows from the current build, with matching cash and order size, at least the configured fee rate, a minimum 60-second embargo, less than 8% drawdown and no invalid depth. Three windows must have closed trades, positive realized net PnL and return, and no open position or orders at the end. The paper drawdown, daily fees, remaining data/ledger gaps, exchange reconciliation and the kill-switch review remain operator attestations; retain the supporting records. Verify the JUnit artifact against the GitHub workflow run and keep the full OOS results, not just the winning windows.

From the intended launch directory, export a human-reviewable candidate profile using the same environment and non-secret settings the service will use. `python -m app.config --describe-mainnet-profile` only prints JSON and does not construct an exchange client or start the engine. Supply no exchange keys to this step. Review the generated file and keep the intended Binance account UID private; it is not an API key.

    PYTHONPATH=. python scripts/go_live_gate.py \
      --i-understand-real-money \
      --overnight-log /path/to/overnight_out.txt \
      --evidence-json /path/to/operator-reviewed-scorecard.json \
      --live-profile /path/to/reviewed-live-profile.json \
      --mainnet-account-uid "$APPROVED_BINANCE_UID" \
      --oos-report /path/to/rolling-walk-forward.json \
      --testnet-junit /path/to/testnet-e2e-results.xml

The gate removes any prior approval stamp before checking and does not change trading mode or submit orders. It writes an approval bound to the build, effective non-secret settings, dedicated account and exact artifact bytes. Keep evidence files at their original absolute paths with restricted write permissions. Legacy, expired or mismatched stamps are rejected at startup, and the exchange account must match before attaching the live journal. A passing gate is not a profitability guarantee. The final mainnet switch still requires the operator's explicit decision and a separately reviewed configuration.

Even an approved installation will not enter a new trade unless it has a current exchange audit of the same local account revision and a successful read-only preflight for the proposed order. The preflight checks exchange account identity, balances, existing orders, fee reserve and whether the rounded position can support a protective exit. It does not override either balances or caps.

The execution cost gate also requires 30 fee-complete, directly measured market fills per side from the same exchange account, network and symbol, in a comparable notional range over the prior seven days. `/status` exposes counts and `/ready` reports missing calibration. Paper, replay, Testnet and synthetic fills cannot stand in for Mainnet measurements; maker and OCO execution are not calibrated by this model. A fresh live journal therefore blocks automatic entry. No automatic calibration or Mainnet bootstrap is authorized by this procedure.

## 4. 20 USDT live-account constraints

- Keep one symbol and one open position only.
- Use exchange-reported free balance and symbol filters; never force a trade to satisfy minimum notional.
- A 5 USDT order can meet the buy minimum but still fail the protective-exit preflight after fees, size rounding and a lower stop price. Treat that as an untradeable configuration rather than increasing a risk cap to force entry.
- Keep API withdrawals disabled and restrict keys by IP.
- Use a conservative order cap, daily loss cap and fee cap appropriate to 20 USDT. The existing 20 USDT candidate profile is not a claim that all symbols can trade at its minimum notional.
- Startup exchange reconciliation and OCO protection must fail closed. Any balance, fill, commission, open-order or local-ledger mismatch blocks new entries.
- Live outcome learning is account-scoped and accepts only exchange-confirmed, fee-complete closed trades. Neither learner may mutate hard risk limits.

## 5. Known limitations (must not be represented as closed)

- Paper does not simulate a true maker queue or queue priority; paper maker results cannot be treated as measured live maker performance.
- Public L2 does not expose hidden liquidity or matching-engine ordering.
- Historical replay is not a complete exchange simulator.
- The live executor remains single-symbol/single-position.
- The live executor performs startup and periodic REST reconciliation. This is not a private order stream, and it does not make external account activity atomic with an order submission. Use a dedicated account and do not trade in it from another process.
- The 20 USDT live account has not been proven profitable or safe merely by configuration. Testnet and real account reconciliation remain mandatory.

## 6. Data retention

Keep the paper SQLite database, market-history captures, overnight reports, OOS reports, Testnet artifacts and operator scorecard together. Snapshot before host migration. Never copy paper account rows into a live ledger.

Use a new directory for each timed, credential-free public Mainnet research capture:

```bash
TRADING_MODE=paper python scripts/capture_multi_symbol.py \
  --symbol btcusdt --seconds 3600 --output-dir data/capture-run-btc-01
python scripts/run_l2_backtest.py data/capture-run-btc-01/btcusdt.jsonl.gz \
  --capture-manifest data/capture-run-btc-01/manifest.json
```

Keep the manifest with the gzip files. `coverage_ok` requires no observed disconnects, depth and trade coverage, an acceptable depth gap, and an archive hash. Insufficient coverage exits with code 2 and does not qualify for manifest-verified replay. A matching hash detects archive changes, not the provenance or statistical quality of the research. Review data quality and retain separate chronological evaluation windows; one capture or one replay is not OOS evidence.

To produce the rolling OOS diagnostics that the approval gate reads, run the following against a sufficiently long, verified recording, with reviewed cash, sizing and fee parameters for the market-entry candidate:

```bash
python scripts/rolling_walk_forward.py /path/to/recording/btcusdt.jsonl.gz \
  --windows 4 --require-capture-manifests \
  --cash "$REVIEWED_CASH" --order-size "$REVIEWED_ORDER_SIZE" --fee "$REVIEWED_FEE_RATE" \
  --output /path/to/rolling-walk-forward.json
```

This diagnostic selects on training data only and evaluates each later, embargo-separated window once. It does not prove the full live execution policy is profitable. Record independent periods and stress realistic execution costs before any deployment decision.
