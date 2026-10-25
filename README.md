# Nexora Quant

**An open, modular crypto-market research and paper-trading platform.**

Nexora Quant is an early-stage research project for learning market microstructure and testing strategies with reproducible simulated execution. It is not investment advice and makes no profit claims.

> **Safety by default:** Binance is used for public market data only. The runtime is paper-only; it rejects any mode other than `TRADING_MODE=paper`. It does not submit real exchange orders or use exchange API credentials.

## Current runtime

- Connects to the public Binance Spot depth diff stream, buffers updates during snapshot acquisition, bridges update IDs, rejects sequence gaps, and resynchronizes after gaps.
- Evaluates the top-of-book bid/ask imbalance only when depth is synchronized.
- Requires a configurable number of consecutive buy signals to reduce one-tick reactions.
- Applies capped free-cash sizing and a centralized pre-trade risk gate.
- Integrates deterministic-configurable simulated adverse slippage, latency, and partial fills into paper entries and exits.
- Supports partial paper exits while preserving the remaining position's cost basis.
- Evaluates paper TP/SL on synchronized best-bid updates while the process is running.
- Persists account and risk state in SQLite, restores on restart, and writes an idempotent paper trade ledger.
- Rolls the daily realized-PnL counter at UTC date change. Consecutive-loss and other non-daily kill switches remain active across the rollover.
- Adds research-only multi-level depth imbalance and heuristic liquidity-wall metrics for synchronized L2 books.
- Adds a compressed gzip JSONL market-event writer and validated chronological replay iterator for reproducible fixtures.

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
| `STARTING_CASH_USDT` | `1000` | Initial paper cash if no saved state exists |
| `ORDER_SIZE_USDT` | `25` | Configured maximum paper entry notional |
| `MAX_ORDER_SIZE_USDT` | `50` | Risk gate cap |
| `SIGNAL_CONFIRMATIONS` | `3` | Consecutive qualifying book updates required before entry |
| `SIMULATED_SLIPPAGE_BPS` | `2` | Mean adverse simulated slippage |
| `SIMULATED_LATENCY_MS` | `100` | Mean simulated execution delay |
| `SIMULATED_PARTIAL_FILL_PROBABILITY` | `0.15` | Probability of a partial simulated fill |
| `SIMULATION_SEED` | `0` | Reproducible pseudo-random simulation seed |
| `TAKE_PROFIT_PCT` | `1.0` | Paper exit threshold above average entry, percent |
| `STOP_LOSS_PCT` | `0.5` | Paper exit threshold below average entry, percent |
| `PAPER_DB_PATH` | `data/paper.sqlite3` | SQLite state and ledger path |

The simulator uses a configurable random seed to make test runs reproducible. Simulated latency delays the paper execution path; it is not a full exchange queue-position or market-impact model.

TP/SL thresholds are checked against the current best bid on synchronized depth updates. They are simulated exits, not exchange-hosted orders; when the process is offline, no exit can trigger until it is running again. If a partial exit occurs, the remaining position continues to be monitored.

## Historical research building blocks

`MarketHistoryWriter` writes compressed JSONL event records and `replay_market_history`
replays them in timestamp order, rejecting malformed or out-of-order records. A caller
must explicitly connect the writer to a feed and choose which exchange/receive timestamps
to preserve; this module is a storage/replay primitive, not yet a complete historical
provider or a millisecond-accurate full-market simulator.

`depth_imbalance` aggregates visible quantities across the best N price levels.
`liquidity_walls` flags levels whose quantity exceeds a multiple of the side's median.
These are descriptive heuristics only: displayed liquidity can be cancelled, and this
L2 feed does not expose individual order identities or true per-order queue position.

## Safety and limitations

- No live order adapter is implemented; actual order submission remains disabled. Do not add API keys to source control or enable real-money trading based only on passing tests.
- This strategy is an educational experiment, not validated or guaranteed to be profitable. Signal confirmation can reduce noise but can also delay entries; it does not establish an edge.
- Top-of-book imbalance is a very simple research signal. It does not yet include a validated backtest, walk-forward testing, out-of-sample evaluation, or market-regime detection.
- Persisted paper state is local to the configured SQLite file. Protect and back up that file; deleting it resets the paper account.
- UTC day rollover resets daily realized PnL only; consecutive-loss and non-daily safety switches remain active.
- CI and unit tests are quality checks, not proof of exchange correctness, production readiness, or profitability.
