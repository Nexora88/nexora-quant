# Nexora Quant

Modular **Binance Spot** research / paper (and optional live) stack:
L2 depth WebSocket, multi-model analysis, fee-aware scalp band, OnlineLearner with anti-overfit, local FastAPI dashboard.

**Not investment advice. No profit guarantee.** Default is **paper**.

## Quick start (Windows paper)

```powershell
cd %USERPROFILE%\nexora-quant
git pull origin main
python -m venv .venv
.\venv\Scripts\Activate.ps1
pip install -e .

copy .env.example .env
# Edit .env — STARTING_CASH_USDT=100, TRADING_MODE=paper, HOST=0.0.0.0

# Optional: clean paper ledger
if (Test-Path data\paper.sqlite3) { Move-Item data\paper.sqlite3 data\paper.sqlite3.bak -Force }

uvicorn app.api:app --host 0.0.0.0 --port 8000
```

- PC: http://127.0.0.1:8000
- Phone (same Wi-Fi): http://PC_IPv4:8000

## Recommended paper risk shape

| Setting | Typical value | Note |
|---------|---------------|------|
| TAKE_PROFIT_PCT | 0.55 | Fee-aware scalp TP |
| STOP_LOSS_PCT | 0.18 | Tight SL; ATR may widen |
| ENTRY_MIN_SCORE | 0.28 | Selective, not frozen |
| MAX_CONCURRENT_POSITIONS | 1 | One position at a time |
| USE_ATR_TARGETS | true | Dynamic TP/SL band |
| LEARNER_FROZEN | false | Learn on paper; true = fixed weights |

See `.env.example`.

## Stack

| Layer | Role |
|-------|------|
| Market | Binance Spot L2 depth WebSocket |
| Analysis | OBI / micro-price / regime / order-flow 1–3s |
| Intelligence | OnlineLearner (anomaly skip, freeze, step clamp), TradeMemory |
| Execution | Paper `ExecutionSimulator.fills` (book walk + impact) or live REST |
| Persistence | AsyncIoQueue → SQLite (WAL); optional L2 JSONL.gz |
| API | FastAPI dashboard (LAN allowed for home Wi-Fi) |

## Paper fills

Paper path calls `ExecutionSimulator.fills` (and `simulate_market_order` alias) with visible L2 levels.
Stop/panic sells use a stress multiplier so thin books do not understate slippage.

## Live (only after paper)

1. 48h+ paper, fee-net expectancy documented
2. API key: withdrawals **off**, IP whitelist
3. Prefer Tokyo VPS — [docs/AWS_TOKYO.md](docs/AWS_TOKYO.md)
4. `TRADING_MODE=live`, keys, `LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY`
5. [docs/GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md)

## Docs

| Doc | Topic |
|-----|-------|
| [docs/HONEST_LIMITS.md](docs/HONEST_LIMITS.md) | Overfit, backtest parity, phase-2 |
| [docs/GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md) | Paper → live |
| [docs/AWS_TOKYO.md](docs/AWS_TOKYO.md) | Low-latency host |
| [docs/DEPLOY_24_7.md](docs/DEPLOY_24_7.md) | Docker / VPS |
| [SECURITY.md](SECURITY.md) | Secrets |

## Honest limits

- Retail RTT loses to co-located HFT on pure TOB imbalance.
- Asymmetric TP/SL improves expectancy math; it does not invent signal quality.
- OnlineLearner can freeze (`LEARNER_FROZEN=true`) so backtests stay comparable.
- No guaranteed returns.

## License

See [LICENSE](LICENSE).
