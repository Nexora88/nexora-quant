# Roadmap

Roadmap items are proposals until implemented and tested.

## Phase 0 — safe foundation
- [x] Public market stream adapter with reconnect/backoff
- [x] Paper-only execution boundary
- [x] Config validation and central pre-trade risk gate
- [x] Basic read-only local API
- [x] CI, lint/test scaffolding, contributor/security docs

## Phase 1 — correctness and observability
- [ ] Run tests and lint in supported Python versions
- [ ] Add structured logs, metrics, and feed-staleness tests
- [ ] Add graceful shutdown and deterministic integration tests
- [ ] Add explicit exchange timestamps and clock-skew policy
- [ ] Add explicit strategy exit lifecycle and closed-trade risk accounting

## Phase 2 — research and replay
- [ ] Historical data ingestion with source attribution
- [ ] Deterministic event replay and backtest runner
- [ ] Train/validation/test split and walk-forward evaluation
- [ ] Fee, spread, latency, slippage, and partial-fill simulation
- [ ] Reports for drawdown, exposure, turnover, and sample-size caveats

## Phase 3 — robust state
- [ ] Durable SQLite ledger and restart recovery
- [ ] Atomic writes, idempotency keys, crash-recovery tests
- [ ] Depth snapshot/diff synchronization with sequence-gap detection
- [ ] Circuit breakers for disconnect storms and malformed feeds

## Phase 4 — user experience
- [ ] Web dashboard with charts, positions, event feed, and risk status
- [ ] Read-only API authentication before remote deployment
- [ ] Watchlists, strategy selection, responsive layout, localization, exports

## Out of scope for initial release
- Live order placement, withdrawals, leverage, and custody of user funds.
- Claims of guaranteed returns or unattended profit generation.
