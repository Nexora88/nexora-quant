# Go-Live Checklist (Nexora Quant)

## Overnight paper (48h)

```bash
TRADING_MODE=paper SYMBOL=btcusdt SYMBOLS=ethusdt,solusdt,bnbusdt \
  uvicorn app.api:app --host 127.0.0.1 --port 8000
```

- Equity curve does not drift from fee-only noise without trades.
- Kill switch and circuit breaker still trip on synthetic loss streak tests.
- `app/expectancy.py` break-even math still matches `effective_fee_rate()` (BNB/VIP).

## Binance API permissions

| Setting | Required |
|---------|----------|
| Enable Reading | Yes |
| Enable Spot & Margin Trading | Yes (live only) |
| Enable Withdrawals | **NEVER** |
| IP whitelist | Your home IP and/or AWS Tokyo elastic IP |

Prefer **testnet** (`BINANCE_TESTNET=true`) until 48h paper is clean.

## Emergency manual

- Binance mobile app logged in, 2FA ready.
- If AWS/internet dies: close position on phone (Spot → sell market).
- Code path: kill switch + OCO + emergency flatten; network outage still needs phone.

## Rate limits

Process-wide `BinanceWeightLimiter` soft-caps REST weight (~2400/min).

## Honest limits

Tokyo RTT ≠ co-location. No profit guarantee.
