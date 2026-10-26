# Paper run → Mainnet live (15 USDT) checklist

## 0. Tokyo prep + weekday L2 harvest (recommended)

1. Launch Ubuntu in **AWS ap-northeast-1** (`t2.micro` / `t3.micro` or small) — [AWS_TOKYO.md](AWS_TOKYO.md).
2. Week: paper multi-pair capture on that host (`SYMBOLS=ethusdt,solusdt,bnbusdt`):

```bash
python scripts/capture_multi_symbol.py
# or: sudo systemctl enable --now nexora-capture
```

3. Before raising size: replay with research gate:

```bash
python scripts/run_l2_backtest.py data/market-history-ethusdt.jsonl.gz --min-score 0.55
```

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
