# AWS Tokyo (ap-northeast-1) — low-latency deploy near Binance Spot

Binance Spot matching is heavily co-located in the Tokyo region. Running the bot on a VPS in **ap-northeast-1** cuts network RTT versus a home PC (often ~80–150 ms → single-digit ms to the public API edge). This **does not** create a guaranteed edge; it only reduces transport lag and slippage risk relative to distant hosts.

## Honest limits

- Retail EC2 is **not** exchange co-location. HFT still wins pure TOB races.
- Prefer paper + L2 capture first; go live only with small size and risk caps.
- Free-tier eligibility and instance types change; verify current AWS Free Tier.

## Minimal Ubuntu EC2 setup

1. Region: **Asia Pacific (Tokyo) ap-northeast-1**
2. Instance: e.g. `t3.micro` / `t3.small` (2 GB+ RAM recommended for depth + SQLite)
3. Security group: outbound HTTPS open; inbound SSH from your IP only; optional TCP 8000 from your IP for dashboard
4. Ubuntu 22.04+ AMI

```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv git
git clone https://github.com/Nexora88/nexora-quant.git
cd nexora-quant
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,perf]"
cp .env.example .env
# edit .env: paper first, SYMBOL / SYMBOLS, asymmetric TP/SL
```

### systemd (24/7)

```bash
sudo cp deploy/nexora-quant.service /etc/systemd/system/
# edit WorkingDirectory and User paths
sudo systemctl daemon-reload
sudo systemctl enable --now nexora-quant
journalctl -u nexora-quant -f
```

### Docker

```bash
docker compose up -d --build
```

## Multi-pair paper capture (week-of-data)

In `.env`:

```bash
TRADING_MODE=paper
SYMBOL=btcusdt
SYMBOLS=ethusdt,solusdt,bnbusdt
MARKET_HISTORY_PATH=data/market-history.jsonl.gz
```

Primary engine still trades `SYMBOL`. Use `scripts/capture_multi_symbol.py` to record L2 history for extra pairs in parallel (research only). Replay with:

```bash
python scripts/run_l2_backtest.py data/market-history-ethusdt.jsonl.gz --min-score 0.55
```

## Latency check

From the instance:

```bash
curl -s -o /dev/null -w '%{time_total}\n' https://api.binance.com/api/v3/ping
# testnet: https://testnet.binance.vision/api/v3/ping
```

Lower is better; still measure end-to-end fill quality in paper before mainnet.

## Security

- API key: **withdrawals disabled**, IP whitelist = this instance public IP only
- Mainnet: `LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY`
- Do not expose dashboard without `NEXORA_API_TOKEN` / JWT

## Event-loop performance (uvloop)

```bash
pip install -e ".[perf]"   # uvloop
# main.py auto-installs uvloop on Linux when importable
```

This improves asyncio scheduling for WebSocket depth; it does **not** equal exchange co-location.
