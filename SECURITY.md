# Security Policy

## Scope

Nexora Quant supports **paper** trading by default and an explicitly gated **live** Binance Spot path.

- Paper mode does not place exchange orders.
- Live mode uses API keys from the environment. Treat them as production secrets.

## Reporting a vulnerability

Do not publish exploitable details in a public issue. Contact the repository owner privately (GitHub profile). Include a minimal reproduction, commit SHA, and impact. Never include real secrets or account data.

## Operational safety

- Prefer binding the dashboard to localhost or protect it with `NEXORA_API_TOKEN` / `NEXORA_JWT_SECRET` and `CORS_ORIGINS`.
- Never commit `.env`, keys, or private trade ledgers.
- On Binance API keys: **withdrawals disabled**, IP whitelist = bot host only.
- Mainnet live requires `LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY` in addition to keys.
- Treat all market data and HTTP payloads as untrusted input.

## Dependency and process hygiene

- Run CI (`ruff`, `pytest`) before promoting config changes.
- Rotate keys if a host is compromised or a key is logged.
