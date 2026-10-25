# Nexora Quant

**An open, modular crypto-market research and paper-trading platform.**

Nexora Quant is an early-stage research project for learning market microstructure and testing strategies with reproducible simulated execution. It is not investment advice and makes no profit claims.

> **Safety by default:** Binance is used for public market data only. The runtime is paper-only; it rejects any mode other than `TRADING_MODE=paper`. It does not submit real exchange orders or use exchange API credentials.

## Current runtime

- Connects to the public Binance Spot depth diff stream.
- Buffers depth events while fetching the REST snapshot, bridges the snapshot update ID, rejects sequence gaps, and reconnects/re-synchronizes after gaps.
- Evaluates the existing top-level bid/ask imbalance strategy only while the depth book is synchronized.
- Applies the central risk gate and capped free-cash sizing for simulated entries.
- Applies configurable paper take-profit and stop-loss exits.
- Persists account and risk state to SQLite, restores them on restart, and writes an idempotent paper trade ledger.
- Exposes the existing local read-only dashboard/API. Keep it bound to localhost unless authentication and deployment hardening have been added.

## Quick start

Requires Python 3.11 or newer.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
python -m app.main
```

Windows PowerShell:

```powershell
py -m venv .venv
.venv\\Scripts\\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m app.main
```

Configuration check: `python -m app.main --once`

Run the read-only API: `uvicorn app.api:app --host 127.0.0.1 --port 8000`

## Configuration

| Variable | Default | Meaning |
|---|---:|---|
| `SYMBOL` | `btcusdt` | Binance Spot market |
| `TRADING_MODE` | `paper` | Only supported mode |
| `STARTING_CASH_USDT` | `1000` | Initial paper cash, used only if no state exists |
| `ORDER_SIZE_USDT` | `25` | Maximum configured paper entry notional |
| `MAX_ORDER_SIZE_USDT` | `50` | Risk gate cap |
| `TAKE_PROFIT_PCT` | `1.0` | Exit threshold above average entry, percent |
| `STOP_LOSS_PCT` | `0.5` | Exit threshold below average entry, percent |
| `PAPER_DB_PATH` | `data/paper.sqlite3` | SQLite state and ledger path |

TP/SL thresholds are checked against the current best bid on each synchronized depth update; they are simulated market exits, not exchange-hosted orders. If the process is offline, no exit can be triggered until it is running again.

## Safety and limitations

- No live order adapter is implemented; actual order submission remains disabled. Do not add API keys to source control or enable real-money trading based only on passing tests.
- This strategy is an educational experiment, not validated or guaranteed to be profitable.
- The synchronized book is used for market data and top-level imbalance; the execution simulator's slippage/partial-fill model is not yet wired into the runtime.
- Persisted paper state is local to the configured SQLite file. Protect and back up that file; deleting it resets the paper account.
- Daily simulated loss values persist across restarts; automatic calendar-day rollover is not implemented yet.
- CI and unit tests are quality checks, not proof of exchange correctness, production readiness, or profitability.
