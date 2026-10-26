# AWS Tokyo (ap-northeast-1) — low-latency deploy near Binance Spot

Binance Spot matching is heavily co-located in the Tokyo region. Running the bot on a VPS in **ap-northeast-1** cuts network RTT versus a home PC (often ~80–150 ms → single-digit ms to the public API edge). This **does not** create a guaranteed edge; it only reduces transport lag and slippage risk relative to distant hosts.

## Honest limits

- Retail EC2 is **not** exchange co-location. HFT still wins pure TOB races.
- Prefer paper + L2 capture first; go live only with small size and risk caps.
- Free-tier eligibility and instance types change; verify current AWS Free Tier.

---

## 1. Tokyo infrastructure (prepare first)

Position the host in **AWS Asia Pacific (Tokyo) ap-northeast-1** on a small Ubuntu machine so retail latency stays low.

| Item | Recommendation |
|------|----------------|
| Region | **ap-northeast-1** (Tokyo) |
| Instance | `t2.micro` / `t3.micro` (free-tier eligible when available) or `t3.small` if depth + multi-pair capture needs more RAM |
| OS | Ubuntu 22.04+ AMI |
| Security group | Outbound HTTPS; inbound SSH from your IP only; optional TCP 8000 from your IP for dashboard |
| Goal | Home broadband 80–150 ms RTT → typically **1–5 ms** to Binance public edge from Tokyo |

```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv git
git clone https://github.com/Nexora88/nexora-quant.git
cd nexora-quant
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,perf]"
cp .env.example .env
# edit .env: paper first, SYMBOL / SYMBOLS, asymmetric TP/SL
mkdir -p data
```

### systemd (engine 24/7)

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

### Latency check

```bash
curl -s -o /dev/null -w '%{time_total}\n' https://api.binance.com/api/v3/ping
# testnet: https://testnet.binance.vision/api/v3/ping
```

Lower is better; still measure end-to-end fill quality in paper before mainnet.

---

## 2. Weekday L2 data harvest (paper only)

Keep **`scripts/capture_multi_symbol.py`** running on the Tokyo host **all week in paper mode**. It accumulates live L2 depth history as `.jsonl.gz` for research pairs so the weekend backtest uses real exchange microstructure, not synthetic ticks.

### `.env` for capture

```bash
TRADING_MODE=paper
SYMBOL=btcusdt
SYMBOLS=ethusdt,solusdt,bnbusdt
MARKET_HISTORY_PATH=data/market-history.jsonl.gz
```

- Primary path: `data/market-history.jsonl.gz` → `SYMBOL` (btcusdt)
- Extra pairs: `data/market-history-ethusdt.jsonl.gz`, `...-solusdt...`, `...-bnbusdt...`

### Run (foreground)

```bash
source .venv/bin/activate
python scripts/capture_multi_symbol.py
```

### Run (systemd, recommended for week-long harvest)

```bash
sudo cp deploy/nexora-capture.service /etc/systemd/system/
# edit WorkingDirectory / User if needed
sudo systemctl daemon-reload
sudo systemctl enable --now nexora-capture
journalctl -u nexora-capture -f
```

Notes:

- Capture is **paper-only**: no orders.
- Bounded per-symbol queues (`max_pending=8000`) drop oldest under volume spikes (backpressure; avoids OOM).
- Prefer `uvloop` via `pip install -e ".[perf]"` on Linux for higher WebSocket throughput.

---

## 3. Accelerated test cycle (weekend replay)

Feed the accumulated real L2 files into the event-driven backtest motor to validate signal quality with **millisecond-level** event order and a strict score gate.

Default CLI gate: **`--min-score 0.55`** (stricter than live engine default `ENTRY_MIN_SCORE=0.32` — research filter).

```bash
# Single pair
python scripts/run_l2_backtest.py data/market-history-ethusdt.jsonl.gz --min-score 0.55

# Other pairs
python scripts/run_l2_backtest.py data/market-history-solusdt.jsonl.gz --min-score 0.55
python scripts/run_l2_backtest.py data/market-history-bnbusdt.jsonl.gz --min-score 0.55
python scripts/run_l2_backtest.py data/market-history.jsonl.gz --min-score 0.55

# Optional knobs
python scripts/run_l2_backtest.py data/market-history-ethusdt.jsonl.gz \
  --min-score 0.55 --cash 1000 --order-size 25 --impact 0.1
```

Output is a JSON summary (trades, PnL, hit-rate style stats from `summarize_l2_result`). Use it to:

1. Confirm the motor does not spam low-quality entries under real depth noise.
2. Tune asymmetry / score threshold **before** raising live size.
3. Compress “one month of learning” into a few days of Tokyo-captured L2 + replay.

---

## Weekly ops plan (summary)

| Phase | Action |
|-------|--------|
| **Mon–Fri** | Tokyo EC2 up; `nexora-capture` (or manual script) writing eth/sol/bnb (+btc) L2 `.jsonl.gz` |
| **Sat morning** | `run_l2_backtest.py … --min-score 0.55` on each file; review JSON summary |
| **Only if healthy** | Optional small paper engine run, then go-live checklist |
| **Live** | Separate process / service; withdrawals off; IP whitelist = this instance |

This path does **not** invent alpha; it shortens the feedback loop with real depth and low network RTT.

## Security

- API key: **withdrawals disabled**, IP whitelist = this instance public IP only
- Mainnet: `LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY`
- Do not expose dashboard without `NEXORA_API_TOKEN` / JWT

## Event-loop performance (uvloop)

```bash
pip install -e ".[perf]"   # uvloop
# main.py and capture_multi_symbol auto-install uvloop on Linux when importable
```

This improves asyncio scheduling for WebSocket depth; it does **not** equal exchange co-location.
