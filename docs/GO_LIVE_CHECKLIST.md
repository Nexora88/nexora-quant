# Paper run → Mainnet live (15 USDT) checklist

## 1. Overnight paper run (VPS)

```bash
# .env
TRADING_MODE=paper
BINANCE_TESTNET=true
SYMBOL=btcusdt
ORDER_SIZE_USDT=15
ENTRY_MIN_SCORE=0.55
```

**systemd** (`/etc/systemd/system/nexora-quant.service`): see `deploy/nexora-quant.service`.

```bash
sudo systemctl enable --now nexora-quant
journalctl -u nexora-quant -f
```

**PM2:**

```bash
pm2 start deploy/ecosystem.config.cjs
pm2 logs nexora-quant
```

### Watch until morning

| Metric | Healthy |
|--------|----------|
| weighted_obi / micro / regime logs | Continuous |
| data_age_seconds | Under max |
| sequence gaps | Rare; auto-resync |
| Database is locked | **None** |

Do not go live if gaps or SQLite locks repeat.

## 2. Binance API hard rules

1. **Enable Withdrawals = OFF**
2. Spot trading only as needed
3. **IP whitelist** = VPS static IP only
4. Dedicated key; rotate if leaked

## 3. Morning → mainnet live (~15 USDT)

```bash
TRADING_MODE=live
BINANCE_TESTNET=false
LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY
ORDER_SIZE_USDT=15
MAX_ORDER_SIZE_USDT=15
MAX_DAILY_LOSS_USDT=5
```

Restart service; confirm `mode=live` and OCO after fills.

Honest limit: 15 USDT validates the stack; it does not beat co-located HFT.
