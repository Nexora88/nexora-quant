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
4. Do not switch to mainnet until every gate in `INSTITUTIONAL_READINESS_SCORECARD.md` is evidenced and approved. A generic `.env` edit is not approval.
5. Dedicated Spot Testnet only before that point; verify reconciliation, OCO, ambiguous-order recovery and cleanup.

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


## 20 USDT sizing policy

- Start with a 5 USDT candidate notional only when the selected symbol's current exchange filters permit it.
- Keep at least 5 USDT uncommitted as a fee, partial-fill and recovery reserve in the initial paper/Testnet profile.
- Scan multiple symbols, but rank only candidates with conservative fee-net edge; no-trade is a valid outcome.
- The future portfolio ceiling is three concurrent positions, not unlimited. Live remains one position until shared cash reservation, per-symbol protection and full account reconciliation are implemented and proven.

## Depth, ledger and edge checks

- **Depth integrity:** `/status` exposes `depth_drops` counters by symbol and reason (`queue_overflow`, `before_resync`, `invalid_or_stale`). A gap or dropped frame clears consecutive signal confirmation; stale frames are not used for new decisions. Depth recordings retain source `exchange_at_ms` (when supplied) and local `received_at_ns` separately from the recording timestamp.
- **Live ledger:** Confirmed orders use a canonical venue/symbol/order key. Recovered OCO executions also include the individual exchange trade ID so two fills for the same child order do not overwrite one another. Existing SQLite files are not rewritten by this change; preserve a backup and review historical raw duplicates before using old exports as evidence.
- **Reconciliation:** A changed local account or an apparent discrepancy against cached history forces a fresh history read. An unresolved mismatch still activates the existing kill switch. These REST reads are not an atomic exchange snapshot; this does not replace private-stream recovery, durable pre-submit intent, or Testnet validation.
- **Edge:** Quality measures alignment for the intended Spot long entry; affordability is checked separately through net edge and the hard gross-to-cost multiple. The alpha estimate is still heuristic. Live entries still require observed execution-cost calibration; this change does not supply initial calibration evidence or authorize Mainnet.
