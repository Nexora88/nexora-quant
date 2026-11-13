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
- No crash / reconnect storm
- Expectancy check script prints `OVERNIGHT_CHECK_PASS`
- Daily loss kill-switch not spurious
- At least a few paper fills over 48h OR honest blockers (not freeze bugs)

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

## 4. Small mainnet
```env
TRADING_MODE=live
BINANCE_TESTNET=false
LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY
STARTING_CASH_USDT=30   # or your real free USDT
MAX_ORDER_SIZE_USDT=15
MAX_DAILY_LOSS_USDT=5
MAX_CONCURRENT_POSITIONS=1
```
Phone: Binance app ready for manual flatten if network dies.

## 5. Explicitly NOT yet
- Multi-position concurrent books
- HFT / co-lo competition (step 5: order-flow accumulation)

## 6. Data to keep
- `data/paper.sqlite3` (learner + memory)
- Snapshot before any host migration

## 7. Automated gate (required for mainnet)

```bash
# After overnight paper passes:
PYTHONPATH=. python scripts/go_live_gate.py --i-understand-real-money \
  --overnight-log /path/to/overnight_out.txt

# Writes data/GO_LIVE_OK — config refuses mainnet live without this stamp
# (unless REQUIRE_GO_LIVE_GATE=false).
```

## 8. Maker entry

Set `PREFER_MAKER=true` so live uses LIMIT_MAKER (post-only) and paper fills near bid.
Fee math + execution now align with maker path when the book fills you.

## 9. Walk-forward (before trusting params)

```bash
PYTHONPATH=. python scripts/walk_forward_params.py path/to/market-history.jsonl.gz
```
