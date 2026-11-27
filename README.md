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
# Keep and back up data\paper.sqlite3; never delete it automatically.

uvicorn app.api:app --host 0.0.0.0 --port 8000
```

| Where | URL |
|-------|-----|
| PC | http://127.0.0.1:8000 |
| Phone (same Wi-Fi) | http://PC_LAN_IP:8000 |

Remote/LAN requests require `NEXORA_API_TOKEN` by default. For a trusted isolated home LAN only, you may explicitly set `NEXORA_ALLOW_LAN=true`; do not use that option on shared/public networks. Localhost remains available without a token.

`git pull` sonrası paper ledger dosyasını **otomatik silme**. Önce yedek al ve pozisyonu/hesap durumunu doğrula; silmek bakiye ve işlem geçmişini geri döndürülemez biçimde kaybettirebilir. Paper hesap artık yeniden başlatmada kayıtlı nakit, maliyet, komisyon ve açık pozisyonu korur; açık pozisyonu atmak yerine `PAPER_RESUME_POSITION=false` ayarında başlangıcı reddeder.

Live modda emir göndermeden önce Binance bakiyesi ve OCO emir geçmişi yeniden uzlaştırılır. Açık pozisyonun borsada koruyucu OCO emri yoksa bot yeni işlem döngüsüne başlamaz; önce korumayı kurmayı dener. Live modda otomatik coin değiştirme kapalıdır; çoklu semboller yalnızca tarama içindir. Live learner yalnızca kendi hesabındaki borsaca doğrulanmış, komisyon muhasebesi tamamlanmış kapanışlardan öğrenir; risk limitleri ve koruma kuralları öğrenilebilir parametre değildir. `LEARNER_FROZEN=true` ile uyarlama ayrıca kapatılabilir.

---

## What the bot does

| Layer | Behavior |
|-------|----------|
| Market | Binance Spot **L2 depth** streams (multi-symbol when `UNIVERSE_AUTO=true`) |
| Router | Ranks majors; autonomous primary switching is paper-only (live executor remains bound to configured symbol) |
| Analysis | OBI, micro-price, regime (trend / range / chop), order-flow pressure |
| Edge gate | Round-trip fee + spread + impact; `min_net_edge_bps` — no edge → no trade |
| Sizing | Kelly + vol target (`RISK_PER_TRADE_PCT`) + impact cap + portfolio budget |
| Targets | ATR dynamic TP / SL / trail (`USE_ATR_TARGETS`); ceiling on SL |
| Exit | TP, SL, **trailing** (peak ratcheted every tick), wick confirm, **`time_stop`** (`MAX_HOLD_SECONDS`) |
| Anti-churn | `MIN_HOLD_SECONDS`, `MAX_TRADES_PER_HOUR`, `ENTRY_COOLDOWN_SECONDS`, `MAX_DAILY_FEE_USDT` |
| Learning | Paper adapts from its own fee-complete closes; live adapts only from its own exchange-confirmed, fee-complete closes; hard risk controls remain immutable (`LEARNER_FROZEN=true` disables adaptation) |
| Recovery | Negative rolling expectancy activates a smaller-size, slightly higher-score probe; it does not permanently deadlock new evidence |
| Paper fills | Depth-aware fills with configured slippage, latency, partial fills, fees, and stressed stop exits |
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

### Multi-regime research validation

Place at least two separate chronological OHLCV CSV files in a directory (one asset per file; columns `timestamp,open,high,low,close,volume`) and run:

```powershell
python scripts/evaluate_profitability.py --data-dir data/ohlcv --train-bars 500 --test-bars 100 --fee-rate 0.001 --slippage-bps 5 --latency-bars 1 --annualization-periods 365 --output data/research-report.json
```

The runner selects parameters only on each training window, evaluates the next unseen window, and reports cross-asset worst windows and per-regime outcomes. Set `--annualization-periods` to match the candle interval (365 daily, 8760 hourly, 525600 one-minute). Results are historical diagnostics, not a forecast.

### OpticOdds and Polymarket research

Compare saved NBA moneyline snapshots with no-vig sportsbook references, size-aware Polymarket asks, and stale-data controls. This offline tool does not place orders or modify the Binance trading engine. See [the snapshot format and runnable example](docs/PREDICTION_MARKET_RESEARCH.md).

### Spot Testnet integration

The normal test suite deliberately skips real network orders. For the isolated, bounded Spot Testnet lifecycle test, add dedicated Testnet-only GitHub Actions secrets and manually run `.github/workflows/spot-testnet-e2e.yml` from `main`. The workflow signs the exact JUnit report with GitHub artifact provenance; the local approval gate verifies that signature, workflow identity, branch and source commit via `gh attestation verify`. The test uses a 20 USDT buy and refuses a competing cleanup sell unless the OCO is confirmed terminal. Do not use mainnet keys.


Fee assumptions are conservative by default: VIP 0 taker fees are used and the BNB discount is **off** unless you explicitly enable it and your account has sufficient BNB and eligible fee payment enabled. Paper maker fills still use the configured fee rate conservatively; verify actual maker/taker commissions from Binance fills before any live use.

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
