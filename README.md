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

## Live (real orders)

1. Overnight paper validation.
2. Binance API key: **withdrawals disabled**, IP whitelist.
3. `.env`: `TRADING_MODE=live`, keys, `BINANCE_TESTNET=false`, `LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY`.
4. Confirm fills + OCO in logs. Emergency flatten if OCO install fails.

See [docs/GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md).

## Design notes

- Compound small wins: redeploy free cash (`COMPOUND_FRACTION`), decide fast (`SIGNAL_CONFIRMATIONS=1` in autonomous mode).
- After every live BUY: `install_protection_or_flatten` places exchange OCO (3 retries); on failure, market-sells and sets emergency + kill switch.
- IO path never blocks the depth loop; queue depth is monitored and exposed on the dashboard snapshot.

## Docs

| Doc | Topic |
|-----|-------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Module map |
| [docs/ARCHITECTURE_GAPS.md](docs/ARCHITECTURE_GAPS.md) | Closed gaps (L2 BT, IO queue, impact, auth) |
| [docs/MS_PIPELINE.md](docs/MS_PIPELINE.md) | Millisecond decision path |
| [docs/QUANT_MICROSTRUCTURE.md](docs/QUANT_MICROSTRUCTURE.md) | OBI / micro-price notes |
| [docs/GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md) | Paper → live |
| [docs/DEPLOY_24_7.md](docs/DEPLOY_24_7.md) | VPS / Docker |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Day-to-day ops |
| [SECURITY.md](SECURITY.md) | Secrets and reporting |

## Honest limits

- Retail latency loses to co-located HFT on pure TOB imbalance.
- Compound small wins (`TAKE_PROFIT_PCT` ~0.45%) are a **capital recycle policy**, not a guaranteed edge.
- L2 memory and learner reduce repeated mistakes; they do not forecast price.
- **Exchange-hosted OCO**: after every live BUY, the bot immediately places OCO (3 retries, ~0.25s backoff). If the exchange returns HTTP 5xx / rejects, `install_protection_or_flatten` market-sells the position and sets `state.emergency` + kill switch — no naked long is left open.
- **SQLite IO queue**: L2 depth never blocks on disk. `AsyncIoQueue` exposes `queue_depth` / `queue_peak` / `dropped_state` every 50 ticks; trades fall back to sync write if the queue is full. Stress-test under 50–100 depth updates/s before sizing capital.

## License

See [LICENSE](LICENSE).
