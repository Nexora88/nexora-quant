# Local operations guide

## Start and stop
Run `python -m app.main` to connect to the public Binance stream and run the paper simulation. Stop with Ctrl+C. Run `python -m app.main --once` to validate configuration without opening a network connection.

## Read-only API
Run `uvicorn app.api:app --host 127.0.0.1 --port 8000`. The health, status, and portfolio endpoints are read-only. Do not bind to 0.0.0.0 or deploy publicly without authentication, request limits, and a security review.

## Configuration changes
Copy `.env.example` to `.env` and change non-secret simulation parameters. The app intentionally rejects trading modes other than `paper`. No Binance API key is needed for public streams.

## Troubleshooting
- Connection unavailable: check network/firewall, Binance public stream availability, and symbol spelling.
- No events: verify the configured symbol exists on Binance Spot and check application logs.
- No paper trade: the signal may not have triggered, the position may already be open, or the risk gate may have rejected entry. Debug logs can explain rejected entries.
- API status has no market data: the API process does not automatically start the market engine. Run the engine process separately in the current version.

## Data and operational caveats
The ledger and runtime state are in memory and disappear on restart. Paper fills do not model realistic slippage, latency, partial fills, or exchange filters. Never use the simulated ledger as a tax, accounting, or investment record.
