# Nexora Quant

Fee-aware **Binance Spot** paper / research desk (optional live): L2 depth WebSocket, multi-coin universe + router, selective scalp band, ATR dynamic targets, anti-churn gates, OnlineLearner with anti-overfit, local FastAPI dashboard.

**Not investment advice. No profit guarantee.** Default mode is **paper**.

This is a **small-compound retail desk** — not “best bot ever.” Edge yoksa trade açmaz; bu özellik, bug değil.

---

## Quick start (Windows PowerShell)

```powershell
cd $env:USERPROFILE\nexora-quant
git pull origin main

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e .

Copy-Item .env.example .env -Force
# Optional: wipe paper ledger after major upgrades
Remove-Item -Force data\paper.sqlite3, paper.sqlite3 -ErrorAction SilentlyContinue

uvicorn app.api:app --host 0.0.0.0 --port 8000
```

| Where | URL |
|-------|-----|
| PC | http://127.0.0.1:8000 |
| Phone (same Wi-Fi) | http://PC_LAN_IP:8000 |

`git pull` sonrası **mutlaka** eski `paper.sqlite3` silinmezse önceki eksi bakiye / açık pozisyon kalabilir.

---

## What the bot does

| Layer | Behavior |
|-------|----------|
| Market | Binance Spot **L2 depth** streams (multi-symbol when `UNIVERSE_AUTO=true`) |
| Router | When **flat**, ranks majors and can switch primary symbol |
| Analysis | OBI, micro-price, regime (trend / range / chop), order-flow pressure |
| Edge gate | Round-trip fee + spread + impact; `min_net_edge_bps` — no edge → no trade |
| Sizing | Kelly + vol target (`RISK_PER_TRADE_PCT`) + impact cap + portfolio budget |
| Targets | ATR dynamic TP / SL / trail (`USE_ATR_TARGETS`); ceiling on SL |
| Exit | TP, SL, **trailing** (peak ratcheted every tick), wick confirm, **`time_stop`** (`MAX_HOLD_SECONDS`) |
| Anti-churn | `MIN_HOLD_SECONDS`, `MAX_TRADES_PER_HOUR`, `ENTRY_COOLDOWN_SECONDS`, `MAX_DAILY_FEE_USDT` |
| Learning | `record_trade` on close; `observe_market` while flat; freeze / anomaly / step clamp |
| Paper fills | Book walk + impact; stress on stop / time_stop sells |
| Dashboard | Equity, fills, blockers, session PnL, learner snapshot, universe board |

---

## Recommended paper shape (100 USDT)

| Setting | Example | Why |
|---------|---------|-----|
| `STARTING_CASH_USDT` | 100 | Small desk |
| `ORDER_SIZE_USDT` | 12 | Cap notional |
| `TAKE_PROFIT_PCT` | 0.55 | Fee-aware scalp TP |
| `STOP_LOSS_PCT` | 0.18 | Tight; ATR may widen |
| `TRAILING_STOP_PCT` | 0.12 | Peak-based trail |
| `ENTRY_MIN_SCORE` | 0.28 | Selective, not frozen |
| `MIN_HOLD_SECONDS` | 180 | Avoid fee churn |
| `MAX_HOLD_SECONDS` | 2700 | Force exit ~45m |
| `MAX_TRADES_PER_HOUR` | 8 | Anti-overtrade |
| `MAX_DAILY_FEE_USDT` | 3 | Fee budget |
| `ENTRY_COOLDOWN_SECONDS` | 45 | Space entries |
| `MAX_CONCURRENT_POSITIONS` | 1 | One position |
| `USE_ATR_TARGETS` | true | Regime-aware band |
| `UNIVERSE_AUTO` | true | Multi-coin screen |

Full defaults: [`.env.example`](.env.example).

---

## Dashboard metrics (session)

- **Saatlik işlem** — entries in the last hour (throttle)
- **Günlük fee** — session fee sum
- **Kapanan** — closed trade count
- **Session PnL** — realized PnL this process session
- **Son çıkış** — last exit reason (`take_profit`, `trailing_stop`, `time_stop`, …)
- **Blockers** — edge / flow / anti-churn reasons

Healthy paper log lines:

```text
in_pos held=…s move=…% peak=… reason=…
anti_churn block: entry_cooldown:…
pulse score=… action=… edge_ok=… blockers=…
```

---

## Stack map

```
Binance L2 WS  →  engine_loop  →  handle_tick
                                    ├─ analyze_market / regime / flow
                                    ├─ exit_reason (peak trail + time_stop)
                                    ├─ score_edge (fee-aware)
                                    ├─ anti-churn gates
                                    ├─ ATR targets + size
                                    └─ paper/live fill → learner
FastAPI /status + dashboard  ←  RuntimeState.snapshot()
```

---

## Live (only after paper)

1. 48h+ clean paper; fee-net expectancy documented  
2. API key: **withdrawals off**, IP whitelist  
3. Prefer low-latency VPS — [docs/AWS_TOKYO.md](docs/AWS_TOKYO.md)  
4. `TRADING_MODE=live` + keys + `LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY`  
5. [docs/GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md)  

Capital discipline (recommended): small float on exchange (e.g. 100 USDT), compound, withdraw excess — do not park large balances.

---

## Docs

| Doc | Topic |
|-----|-------|
| [docs/HONEST_LIMITS.md](docs/HONEST_LIMITS.md) | Overfit, fees, what this is not |
| [docs/GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md) | Paper → live |
| [docs/AWS_TOKYO.md](docs/AWS_TOKYO.md) | Low-latency host |
| [docs/DEPLOY_24_7.md](docs/DEPLOY_24_7.md) | Docker / VPS |
| [docs/SCALP_MODE.md](docs/SCALP_MODE.md) | Scalp band notes |
| [SECURITY.md](SECURITY.md) | Secrets |

---

## Tests

```powershell
python -m pytest tests/ -q
```

Core coverage includes config, decision, edge gate, ATR, learner, exit peak/trail, fees/regime.

---

## Honest limits

- Retail RTT loses to co-located HFT on pure TOB imbalance.
- Asymmetric TP/SL improves *expectancy math*; it does not invent alpha.
- Most retail bots lose to **fees + overtrading + wrong regime** — anti-churn exists for that.
- OnlineLearner needs **closed trades** to adapt; one open zombie taught nothing (fixed via peak + time_stop).
- Paper can still show losses; success metric: **fee-net expectancy > 0** and controlled churn.
- **No guaranteed returns.**

---

## License

See [LICENSE](LICENSE).
