# Architecture and trust boundaries

## Components
- Market-data adapter: consumes public Binance Spot WebSocket streams and reconnects with capped exponential backoff.
- Runtime state: tracks latest quote, recent trades, connection metadata, and paper portfolio access. State is in-memory.
- Strategy: emits a research signal from top-of-book quantities. It cannot submit orders.
- Risk manager: evaluates paper entries against notional, cash, spread, feed freshness, and kill-switch rules.
- Paper executor: simulates fills, fees, balances, inventory, and a simple trade ledger.
- FastAPI: exposes read-only local status and portfolio snapshots.

## Trust boundaries
External market data is untrusted. Strategy output is untrusted until checked by the risk gate. Execution remains paper-only. API endpoints are not authenticated and must not be exposed publicly.

## Market data caveats
The Binance bookTicker stream supplies best bid/ask, not a full order book. No depth snapshot/diff sequence synchronization is implemented. Receipt timestamps are local receive times, not exchange timestamps.

## State and restart behavior
Runtime state is memory-only. Durable ledger storage, migrations, idempotent replay, and crash recovery are not implemented. Do not rely on the process as a financial record.

## Risk controls
Risk checks are guardrails, not guarantees. Loss-streak logic activates when closed trades are recorded; the current simple signal loop does not implement an automatic exit policy. Do not present it as a fully managed strategy.
