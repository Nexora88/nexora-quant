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

## Tokyo weekly cycle (recommended before live)

Full detail: [AWS_TOKYO.md](AWS_TOKYO.md).

1. **Infrastructure** — EC2 in **ap-northeast-1** (`t2.micro` / `t3.micro` or small Ubuntu). Cut retail RTT vs home PC.
2. **Weekday L2 harvest** — paper-only multi-pair capture on the Tokyo host:

```bash
# .env
TRADING_MODE=paper
SYMBOL=btcusdt
SYMBOLS=ethusdt,solusdt,bnbusdt

# one-shot or systemd
python scripts/capture_multi_symbol.py
# sudo systemctl enable --now nexora-capture
```

Writes `data/market-history.jsonl.gz` and `data/market-history-{eth,sol,bnb}usdt.jsonl.gz`.

3. **Accelerated backtest** — replay with a strict research score gate:

```bash
python scripts/run_l2_backtest.py data/market-history-ethusdt.jsonl.gz --min-score 0.55
python scripts/run_l2_backtest.py data/market-history-solusdt.jsonl.gz --min-score 0.55
python scripts/run_l2_backtest.py data/market-history-bnbusdt.jsonl.gz --min-score 0.55
```

Only proceed toward live size after summaries look coherent (no runaway trade count, acceptable expectancy under impact).

## Live

1. Overnight paper — check logs for sequence gaps / `Database is locked`.
2. Binance key: no withdrawals, IP whitelist.
3. Prefer Tokyo host ([AWS_TOKYO.md](AWS_TOKYO.md)).
4. `.env`: `TRADING_MODE=live`, keys, `BINANCE_TESTNET=false`, `LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY`.
5. Restart service; confirm `mode=live` and fills / OCO in logs.

Details: [GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md), [deploy/](../deploy/).

## Useful commands

```bash
pytest
ruff check .
python scripts/capture_multi_symbol.py
python scripts/run_l2_backtest.py data/market-history.jsonl.gz --min-score 0.55
```

## Logs to watch

- `Engine started mode=...`
- `capturing symbol=...` / writer stats (harvest)
- `Learner restored` / `Memory restored` / `Motor restored`
- `LIVE BUY` / `OCO` (live only)
- Kill switch / emergency flatten reasons
- `io_queue_stats` under stress
