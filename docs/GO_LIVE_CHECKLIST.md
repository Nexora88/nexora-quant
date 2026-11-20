# Go-Live Checklist (testnet → small mainnet)

## 0. Philosophy
- One open position only (`MAX_CONCURRENT_POSITIONS=1`).
- Expectancy is fee-aware; do not lower fees to force trades.
- ATR + vol-target size the ticket; fixed .env TP/SL are baselines only.

## 1. Overnight paper (48h)
```bash
# .env: TRADING_MODE=paper, STARTING_CASH_USDT=100, USE_ATR_TARGETS=true
uvicorn app.api:app --host 127.0.0.1 --port 8000
# other terminal:
PYTHONPATH=. python scripts/overnight_paper_check.py
```
Pass criteria:
- A durable paper session spans at least 48 hours and is recently active/cleanly stopped
- At least 1,000 primary depth ticks and 20 fee-complete closed paper trades
- Closed-trade expectancy is positive after entry and exit fees
- Expectancy check script prints `OVERNIGHT_CHECK_PASS`
- Review reconnects, daily-loss behavior, and logs; the script does not replace manual review

## 2. Binance API (both testnet and mainnet)
Create API key with:
- **Enable Reading**: YES
- **Enable Spot & Margin Trading**: YES
- **Enable Withdrawals**: **NO** (never)
- IP whitelist: your VPS / home IP only

## 3. Testnet first
```env
TRADING_MODE=live
BINANCE_TESTNET=true
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
# do NOT set LIVE_CONFIRM yet
```
Confirm OCO protect + flatten on a tiny notional.

## 4. Mainnet remains blocked until institutional gates pass

Do not copy a generic mainnet .env block or enable mainnet based only on a successful unit-test run. Require the scorecard evidence: exact-commit CI green, Spot Testnet E2E green, at least 48 hours of durable paper evidence, fee-net positive OOS results across multiple regimes, exchange/ledger reconciliation, and an operator-reviewed kill-switch procedure. Until then, use PAPER or dedicated Spot Testnet only. If/when approved, use the actual free USDT balance and live symbol filters; never copy a fixed notional from this document.

## 5. Explicitly NOT yet
- Multi-position concurrent books (planned ceiling: at most three for a 20 USDT wallet, but live remains one until shared-wallet and per-symbol OCO reconciliation is proven)
- Autonomous symbol switching in live mode (the live executor is bound to one configured symbol; other streams are scan-only)
- Online learner updates in live mode (policy remains frozen until independent multi-regime validation)
- HFT / co-lo competition (step 5: order-flow accumulation)

## 6. Data to keep
- `data/paper.sqlite3` (learner + memory)
- Snapshot before any host migration

## 7. Automated gate (required for mainnet)

```bash
# After overnight paper passes:
PYTHONPATH=. python scripts/go_live_gate.py --i-understand-real-money \
  --overnight-log /path/to/overnight_out.txt

# Writes a source-fingerprinted data/GO_LIVE_OK approval after the real paper checks.
# The stamp expires after 7 days and any runtime source change invalidates it.
# Mainnet cannot disable or bypass this gate through an environment variable.
```

## 8. Maker entry

Set `PREFER_MAKER=true` so live uses LIMIT_MAKER (post-only) and paper fills near bid.
Fee math + execution now align with maker path when the book fills you.

## 9. Walk-forward (before trusting params)

Enable `MARKET_HISTORY_ENABLED=true` during a separate paper collection period, then run:

```bash
PYTHONPATH=. python scripts/walk_forward_params.py path/to/market-history.jsonl.gz --fee 0.001
```

The script selects parameters on the training segment and evaluates only the selected candidate on the later unseen segment. Repeat on rolling windows, multiple symbols, and distinct market regimes; one split is not proof of robustness.


## Mandatory integration evidence

- [ ] Run `.github/workflows/spot-testnet-e2e.yml` manually with dedicated Spot Testnet credentials and a 10?25 USDT test amount. Confirm the uploaded artifact is green and the testnet account has no residual test position or open OCO list.
- [ ] Verify the exchange's `listClientOrderId` lookup path after simulating a lost OCO HTTP response; unit coverage is not a substitute for a testnet run.
- [ ] Confirm OCO cancellation is visible in `openOrderLists` before any emergency market exit.
- [ ] Run rolling multi-asset research with separate chronological CSVs covering trend, range, choppy and stressed periods; inspect worst-window drawdown and net results.
- [ ] Reconcile a live account's free/locked balances, order lists, actual fills, commission assets and local ledger before any strategy order.
- [ ] Keep the strategy learner frozen in mainnet. Do not promote weights from paper without a separate, reproducible out-of-sample approval process.


## 10. 20 USDT account sizing reality

The 20 USDT candidate profile is Testnet-first, with a 5 USDT order cap and a 5 USDT minimum-order assumption only as a placeholder. Binance symbol filters are authoritative and vary by symbol and order type. The scanner must reject any candidate whose exchange minimum, quantity step, fees, spread, and conservative slippage do not fit the available quote balance and net-edge threshold. Do not increase the cap automatically to satisfy a symbol minimum. A 20 USDT wallet does not justify unlimited concurrent orders: the intended future hard ceiling is three, with a cash/fee reserve; current live routing remains one position.
