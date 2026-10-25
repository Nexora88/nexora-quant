# Nexora Quant

**An open, modular crypto-market research and paper-trading platform.**

Nexora Quant is designed for individual researchers, students, developers, and contributors who want to study market microstructure, build/test strategies, and compare simulated execution against reproducible data. It is not a profit promise or financial advice.

> **Safety by default:** the initial release uses Binance public market streams and simulated paper execution only. No exchange API keys are required, and no live-order endpoint is implemented.

## Project status

Early-stage research software. APIs and strategy behavior may change. Passing unit tests does not prove profitability, exchange correctness, or production readiness.

## Goals

- Public Binance Spot market-data ingestion with reconnect/backoff and explicit feed health.
- Event-driven, testable strategy interface separated from execution.
- Central risk gate for all simulated entries.
- Paper portfolio with fees, realized/unrealized PnL, trade ledger, and configurable assumptions.
- Local read-only dashboard plus API endpoints for health, status, and portfolio snapshots.
- Reproducible tests, linting, CI, safe configuration, and contributor documentation.
- Clear provider timestamps, source limitations, and graceful shutdown.

## Quick start

Requires Python 3.11 or newer.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
python -m app.main
```

Windows PowerShell:
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m app.main
```

Run a configuration check:
```bash
python -m app.main --once
```

Run the local read-only API:
```bash
uvicorn app.api:app --host 127.0.0.1 --port 8000
```
Open `http://127.0.0.1:8000/` for the live read-only dashboard, or `/health`, `/status`, and `/portfolio` for JSON endpoints. The API process starts the market-data engine. Keep it bound to localhost unless you have added authentication and deployment hardening.

## Architecture

```text
Binance public WebSocket
        │
        ▼
Market-data adapters ──► normalized events ──► state/health
                                                  │
                                                  ▼
                                           strategy interface
                                                  │ signal only
                                                  ▼
                                      risk and circuit-breaker gate
                                                  │ approved intent
                                                  ▼
                                          paper execution
                                                  │
                                  ledger / portfolio / API snapshots
```

Strategy modules produce intents only. They must not import exchange order clients or bypass the risk gate. The paper executor is the only execution adapter included in this phase.

## Configuration

Copy `.env.example` to `.env`. Settings are validated at startup. Never put real credentials in the repository. The app deliberately rejects any mode other than `paper`. New research helpers in this branch provide capped free-cash sizing, a SQLite paper ledger, deterministic execution-friction simulation, and sequence-aware depth-book primitives. These are library components; they are not yet wired into the running engine or the dashboard.

## Risk and safety defaults

- Live order submission, withdrawals, account endpoints, and credential storage are out of scope for this release.
- Entries are blocked when the feed is stale, the spread is too wide, the requested size exceeds configured limits, available cash is insufficient, or the kill switch is active.
- Loss limits are simulation controls, not a guarantee against losses or bugs.
- A simulated kill switch prevents new entries; it does not claim to liquidate an exchange position.
- Do not expose the local API to the public internet without authentication, rate limiting, and deployment security review.
- Paper fills are simplified and cannot predict real execution quality.

## Known limitations

- The `bookTicker` stream supplies best bid/ask, not a full depth book. This is not a synchronized order-book depth implementation.
- The initial strategy is an educational top-of-book imbalance experiment, not a validated trading strategy.
- The new SQLite ledger, execution simulator, and depth-book synchronizer are standalone research components with unit tests; runtime integration, REST snapshot fetching/buffer replay, automatic TP/SL exits, and restart recovery of the live engine are not yet complete. Multi-user authentication is also absent. The included dashboard is an initial read-only monitor, not a full trading workstation.
- CI and local tests are quality checks, not proof of profitability or production safety.

## Development

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
```

Please read [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before contributing.

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md). Work should be merged in small, tested increments. Do not add live execution without a separate threat model, testnet-only validation, explicit opt-in, and independent review.

## License

MIT. See [LICENSE](LICENSE).

## Disclaimer

Nexora Quant is software for educational, research, and simulation purposes. It is not investment advice, a signal service, or a guarantee of returns. Crypto assets are volatile and users can lose money. You are responsible for your own decisions and for complying with applicable laws and exchange terms.
