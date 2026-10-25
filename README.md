# Nexora Quant

**An open, modular crypto-market research and paper-trading platform.**

Nexora Quant is an early-stage research project for learning market microstructure and testing strategies with reproducible simulated execution. It is not investment advice and makes no profit claims.

> **Default safety:** `TRADING_MODE=paper` is the default and uses simulated fills. The codebase also contains an explicitly gated `live` adapter that can submit real Binance Spot orders if configured. This branch does not remove or validate that adapter. Keep paper mode enabled, do not add real API keys, and do not treat this project as a profit-proven system.

## Current runtime

- Connects to the public Binance Spot depth diff stream, buffers updates during snapshot acquisition, bridges update IDs, rejects sequence gaps, and resynchronizes after gaps.
- Evaluates the top-of-book bid/ask imbalance only when depth is synchronized.
- Requires a configurable number of consecutive buy signals to reduce one-tick reactions.
- Applies capped free-cash sizing and a centralized pre-trade risk gate.
- Simulates configurable latency, adverse slippage, square-root/linear impact, visible-book walking and partial fills for paper entries and exits. When a synchronized L2 snapshot is available, paper market orders consume the supplied visible ask levels (buys) or bid levels (sells) and use the consumed levels’ VWAP before applying the impact/slippage penalty.
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

Run the read-only API: `uvicorn app.api:app --host 127.0.0.1 --port 8000`. Keep it bound to localhost. Direct non-loopback requests are denied unless `NEXORA_API_TOKEN` is set and sent as `Authorization: Bearer <token>`. A local reverse proxy can make remote clients appear loopback; configure authentication at the proxy and do not expose this API publicly without reviewing proxy trust and deployment settings.

## Configuration

| Variable | Default | Meaning |
|---|---:|---|
| `SYMBOL` | `btcusdt` | Binance Spot market |
| `TRADING_MODE` | `paper` | `paper` or gated `live`; use paper for research only |
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
| `MARKET_HISTORY_PATH` | `data/market-history.jsonl.gz` | Compressed local L2 observation log |
| `NEXORA_API_TOKEN` | unset | Optional bearer token required for non-loopback API requests; never commit real tokens |

The simulator uses a configurable random seed to make test runs reproducible. Simulated latency delays the paper execution path. Visible-book walking is snapshot-based: it does not replay order-book changes during the delay, infer hidden liquidity, or reproduce matching-engine queue priority. Impact is a heuristic penalty, not a calibrated market-impact law.

TP/SL thresholds are checked against the current best bid on synchronized depth updates. They are simulated exits, not exchange-hosted orders; when the process is offline, no exit can trigger until it is running again. If a partial exit occurs, the remaining position continues to be monitored.

## Historical research building blocks

`MarketHistoryWriter` writes compressed JSONL event records and `replay_market_history`
replays them in timestamp order, rejecting malformed or out-of-order records. The paper runtime records synchronized public L2 observations to this path. `app/research_replay.py` adds an event-time replay harness that applies depth snapshots and explicit cancellation/depletion events before filling orders after configured latency. It computes visible-book VWAP, partial/unfilled quantity, and fees. Feed quality, missing events, exchange-versus-receive timestamps, and hidden liquidity still limit fidelity; this is a research replay, not exchange-grade execution.

`depth_imbalance` aggregates visible quantities across the best N price levels.
`liquidity_walls` flags levels whose quantity exceeds a multiple of the side's median.
These are descriptive heuristics only: displayed liquidity can be cancelled, and this
L2 feed does not expose individual order identities or true per-order queue position.

## Safety and limitations

- A live order adapter exists behind `TRADING_MODE=live` and configuration checks; it can submit real Binance Spot orders. It is not the default. Mainnet requires API keys, `BINANCE_TESTNET=false`, and the explicit `LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY` acknowledgement. Keep withdrawals disabled and restrict the API key by IP. Testnet end-to-end validation and independent net-of-cost evaluation have not yet been verified by this change; never commit API keys.
- This strategy is an educational experiment, not validated or guaranteed to be profitable. Signal confirmation can reduce noise but can also delay entries; it does not establish an edge.
- The strategy is a collection of research heuristics, not an independently validated trading edge. Visible-book execution is still only an approximation; no simulator can reproduce all cancellations, hidden liquidity, queue priority, network jitter, matching-engine rules, or sudden market shocks. Ask-wall/whale detection is a heuristic and cannot identify the owner or intent behind displayed orders. It can miss spoofing and can block valid entries.
- Persisted paper state is local to the configured SQLite file. Protect and back up that file; deleting it resets the paper account.
- UTC day rollover resets daily realized PnL only; consecutive-loss and non-daily safety switches remain active.
- CI and unit tests are quality checks, not proof of exchange correctness, production readiness, or profitability.

## Research intelligence: mathematics, market physics, and large-order risk

The engine combines several *hypotheses*, not a guaranteed autonomous profit engine:

- **Microstructure:** visible bid/ask imbalance, weighted depth imbalance, micro-price premium, spread, and short-window momentum.
- **Statistics/regimes:** an Ornstein–Uhlenbeck-style mean-reversion tracker and coarse trend/sideways plus normal/high-volatility labels. The historical `regime_adaptive` baseline follows momentum only in uptrends, tests mean reversion only in normal-volatility sideways conditions, and stays flat in high-volatility or unknown regimes. This is a conservative baseline to compare, not an established best strategy.
- **Risk and expected edge:** an explainable weighted-vote decision, adverse-selection checks, a cost-aware edge gate, capped sizing, and kill switches. Kelly-style sizing is only as reliable as its estimated win probability and payoff distribution; estimation error can make it dangerously aggressive.
- **Large displayed orders:** a persistent ask-wall heuristic blocks new long entries when its signal is strong enough. This is deliberately conservative, but displayed size is not proof of a whale, and spoofing/cancellation can defeat the signal. The engine cannot identify individual traders from public aggregate L2 data.
- **Execution physics approximation:** paper market orders walk the supplied visible L2 levels and use the consumed-level VWAP, then apply adverse slippage/impact. If the visible book cannot cover the requested size, the simulated fill is capped to available quantity. Latency is simulated, but the book is not refreshed during that delay.

Use `validate_multiple_assets` to run rolling chronological train/test windows independently per supplied asset; it reports the worst test-window return and maximum drawdown across assets. Backtest summaries also report the worst period return and a simple 5% lower-tail mean. Event replay supports latency and cancellation/depletion cases. For a proper stress suite, include sudden spread widening, book thinning, adverse price gaps, fee increases, delayed/cancelled data, and partial fills as explicit fixtures. Do not tune against test windows. Judge net-of-fees expectancy, maximum drawdown, tail losses, turnover, and stability—not a single profitable run. These helpers are research primitives and have not been runtime-validated in this connector session.

## Historical strategy comparison and walk-forward research

```python
from app.backtesting import BacktestConfig, compare_strategies, load_ohlcv_csv, walk_forward

candles = load_ohlcv_csv("data/btcusdt_1h.csv")
candidates = [
    {"strategy": "buy_and_hold", "params": {}},
    {"strategy": "momentum", "params": {"lookback": 12}},
    {"strategy": "sma_cross", "params": {"fast": 5, "slow": 24}},
    {"strategy": "mean_reversion", "params": {"window": 20, "entry_z": 1}},
]
cfg = BacktestConfig(fee_rate=0.001, slippage_bps=3, latency_bars=1)
print(compare_strategies(candles, candidates, cfg))
print(walk_forward(candles, candidates, cfg))
```

CSV requires `timestamp,open,high,low,close` and optionally `volume`; timestamps must be
strictly increasing integers. Available baselines are buy-and-hold, simple moving-average
cross, momentum, and mean-reversion. The engine charges configurable fees and adverse
slippage on turnover, delays signals by whole bars, reports net return, annualized Sharpe,
maximum drawdown, trade count, cost estimate, profit factor, and coarse volatility/trend
regime slices.

**Important research caveats:** this initial simulator uses close-to-close returns and
bar-delayed execution, not tick-level fills or a full order-book replay. It does not model
funding, borrow, spread, market impact, delisted assets, survivorship bias, or intrabar
stop execution. The unseen segment is chronological and kept separate from parameter
selection, but one holdout is not enough: repeat rolling walk-forward windows across
multiple assets and market periods. Never select a strategy from its training score alone.
Positive historical results do not guarantee future profits. A gated live adapter exists elsewhere in the codebase; the OHLCV backtester does not test it, and this paper simulator does not establish that live results will match simulated results.
