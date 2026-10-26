# Nexora Quant

Modular **Binance Spot** research and trading stack: L2 depth stream, multi-model analysis, compound paper/live execution, and a local dashboard.

Not investment advice. **No profit guarantee.** Default mode is paper (simulated fills).

## What it does

| Layer | Role |
|--------|------|
| **Market data** | Binance depth diff + snapshot sync, gap recovery |
| **AnalysisMotor** | Kinematics, geometric compound path, HH/HL structure, OBI/micro, regime |
| **TrendFollower** | Fast/slow momentum; long only when aligned up |
| **Decision** | Feature votes; `AUTONOMOUS_MODE` softens edge/noise/adverse blocks |
| **OnlineLearner** | grow / protect / rebuild from trade PnL (persisted) |
| **TradeMemory** | Setup keys `regime|structure|bias` — avoid toxic, boost proven |
| **Execution** | Paper simulator (impact + book walk) or live REST + optional OCO |
| **Risk** | Size caps, daily loss, consecutive losses, kill switch, spread/age gates |
| **Dashboard** | FastAPI `/status` + simple UI |

## Safety

- `TRADING_MODE=paper` (default) — no real orders.
- `TRADING_MODE=live` + `BINANCE_TESTNET=true` — testnet keys.
- Mainnet live requires **all** of:
  - `BINANCE_TESTNET=false`
  - `BINANCE_API_KEY` / `BINANCE_API_SECRET`
  - `LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY`
- Disable **withdrawals** on the API key; whitelist VPS IP only.

## Quick start

Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\\Scripts\\activate
python -m pip install -e ".[dev]"
cp .env.example .env
python -m app.main
```

Optional dashboard:

```bash
uvicorn app.api:app --host 127.0.0.1 --port 8000
```

### Minimal `.env` (paper)

```bash
SYMBOL=btcusdt
TRADING_MODE=paper
AUTONOMOUS_MODE=true
COMPOUND_FRACTION=0.85
ORDER_SIZE_USDT=10
MAX_ORDER_SIZE_USDT=25
TAKE_PROFIT_PCT=0.45
STOP_LOSS_PCT=0.35
ENTRY_MIN_SCORE=0.32
```

### Live mainnet (after paper is clean)

```bash
TRADING_MODE=live
BINANCE_TESTNET=false
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY
ORDER_SIZE_USDT=10
MAX_DAILY_LOSS_USDT=5
```

See [docs/GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md) and [deploy/](deploy/).

## Research tools

```bash
python scripts/run_l2_backtest.py data/market-history.jsonl.gz --min-score 0.55
```

```python
from app.l2_backtest import L2BacktestConfig, run_l2_backtest, summarize_l2_result
from app.backtesting import BacktestConfig, compare_strategies, load_ohlcv_csv
```

OHLCV bar backtests cannot validate pure L2 imbalance; use `app.l2_backtest` for depth fixtures.

## Tests / quality

```bash
python -m pip install -e ".[dev]"
ruff check .
pytest
```

## Docs

| Doc | Topic |
|-----|--------|
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
- Exchange-hosted TP/SL (OCO) only applies when the live path successfully places them.

## License

See [LICENSE](LICENSE).
