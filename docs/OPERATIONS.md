# Operations

## Paper (default)

```bash
cp .env.example .env
# TRADING_MODE=paper
python -m app.main
```

Stop with Ctrl+C. State: `data/paper.sqlite3`. L2 capture: `MARKET_HISTORY_PATH`.

## Dashboard

```bash
uvicorn app.api:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000/
```

Remote access: set `NEXORA_API_TOKEN` or `NEXORA_JWT_SECRET`.

## Live

1. Overnight paper — check logs for sequence gaps / `Database is locked`.
2. Binance key: no withdrawals, IP whitelist.
3. `.env`: `TRADING_MODE=live`, keys, `BINANCE_TESTNET=false`, `LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY`.
4. Restart service; confirm `mode=live` and fills / OCO in logs.

Details: [GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md), [deploy/](../deploy/).

## Useful commands

```bash
pytest
ruff check .
python scripts/run_l2_backtest.py data/market-history.jsonl.gz
```

## Logs to watch

- `Engine started mode=...`
- `Learner restored` / `Memory restored`
- `LIVE BUY` / `OCO` (live only)
- Kill switch reasons
