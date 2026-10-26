# Nexora Quant

Modular **Binance Spot** research and trading stack: L2 depth stream, multi-model analysis, compound paper/live execution, and a local dashboard.

Not investment advice. **No profit guarantee.** Default mode is paper (simulated fills).

## Stack

| Layer | Role |
|-------|------|
| **Market** | Binance Spot REST + depth WebSocket (L2) |
| **Analysis** | Multi-model `AnalysisMotor` (kinematics, compound geo-mean, structure, microstructure, regime) |
| **Intelligence** | OnlineLearner (grow/protect/rebuild), TradeMemory (setup lessons), TrendFollower |
| **Execution** | Paper simulator (impact + book walk) or live REST + optional OCO |
| **Persistence** | Non-blocking `AsyncIoQueue` → SQLite; L2 history JSONL.gz |
| **API** | FastAPI dashboard (auth, rate limit) |

## Quick start (paper)

```bash
cp .env.example .env
pip install -e ".[dev]"
python -m app.main
# dashboard: uvicorn app.api:app --host 127.0.0.1 --port 8000
```

Default risk shape is **asymmetric**: `TAKE_PROFIT_PCT=1.20`, `STOP_LOSS_PCT=0.35` (≥ `MIN_REWARD_RISK_RATIO=2`). With ~0.1% fees each way, break-even win rate is under ~40% (see `app/expectancy.py`).

## Live (real orders)

1. Overnight paper validation.
2. Binance API key: **withdrawals disabled**, IP whitelist.
3. Prefer host in **AWS Tokyo (ap-northeast-1)** — [docs/AWS_TOKYO.md](docs/AWS_TOKYO.md).
4. `.env`: `TRADING_MODE=live`, keys, `BINANCE_TESTNET=false`, `LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY`.
5. Confirm fills + OCO in logs. Emergency flatten if OCO install fails.

See [docs/GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md).

## Multi-pair L2 capture (research)

```bash
# .env: SYMBOL=btcusdt  SYMBOLS=ethusdt,solusdt,bnbusdt
python scripts/capture_multi_symbol.py
python scripts/run_l2_backtest.py data/market-history-ethusdt.jsonl.gz --min-score 0.55
```

## Design notes

- Compound: redeploy free cash (`COMPOUND_FRACTION`), decide fast in autonomous mode.
- After every live BUY: `install_protection_or_flatten` places exchange OCO (3 retries); on failure, market-sells and sets emergency + kill switch.
- IO path never blocks the depth loop; queue depth is monitored on the dashboard snapshot.

## Docs

| Doc | Topic |
|-----|-------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Module map |
| [docs/ARCHITECTURE_GAPS.md](docs/ARCHITECTURE_GAPS.md) | Closed gaps (L2 BT, IO queue, impact, auth) |
| [docs/MS_PIPELINE.md](docs/MS_PIPELINE.md) | Millisecond decision path |
| [docs/QUANT_MICROSTRUCTURE.md](docs/QUANT_MICROSTRUCTURE.md) | OBI / micro-price notes |
| [docs/GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md) | Paper → live |
| [docs/DEPLOY_24_7.md](docs/DEPLOY_24_7.md) | VPS / Docker |
| [docs/AWS_TOKYO.md](docs/AWS_TOKYO.md) | Tokyo EC2 low-latency + multi-pair capture |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Day-to-day ops |
| [SECURITY.md](SECURITY.md) | Secrets and reporting |

## Honest limits

- Retail latency loses to co-located HFT on pure TOB imbalance; Tokyo VPS only cuts **network** RTT, not matching-engine co-lo.
- Asymmetric TP/SL improves **mathematical expectancy** at a given win-rate; it does not invent signal quality.
- Compound small/medium wins are a **capital recycle policy**, not a guaranteed edge.
- L2 memory and learner reduce repeated mistakes; they do not forecast price.
- **Exchange-hosted OCO**: after every live BUY, OCO is placed with retries; failure triggers emergency flatten + kill switch.
- **SQLite IO queue**: depth path never blocks on disk; monitor `io_queue_stats` under stress.

## License

See [LICENSE](LICENSE).
