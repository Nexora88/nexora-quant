# Profit path (honest) — 100 → 140–150

**No guarantee.** This document is an operating protocol, not a promise.

## Reality check

- Spot VIP0 round-trip is ~15–20 bps (BNB) to ~20 bps (no BNB) before spread/impact.
- Scalp TP 0.40–0.90% leaves a thin net band after fees.
- 100 USDT desk: few trades → high variance. 40–50% equity gain needs **repeated fee-net positive expectancy**, not one lucky session.

## Protocol (paper first)

1. Wipe ledger: delete `data/paper.sqlite3`.
2. Run **strict paper** for 48–72h with `PAPER_SOFT_GATES=false` once you have ≥20 closed trades under soft gates.
3. Dashboard must show:
   - `session_expectancy.expectancy_usdt > 0`
   - `maker_stats.timeout_rate < 0.30` (if `PREFER_MAKER=true`)
   - max drawdown within `MAX_DAILY_LOSS_USDT`
4. If expectancy < 0 after `EXPECTANCY_MIN_TRADES` (default 12), the engine **halts new entries** until fee-net recovers (adaptive gate).
5. Only then: testnet E2E → `scripts/go_live_gate.py` → mini mainnet (50–100 USDT).

## Settings that improve survival (not magic)

| Knob | Prefer | Why |
|------|--------|-----|
| `PREFER_MAKER` | true | Cuts entry fee; largest single lever |
| `FEE_USE_BNB_DISCOUNT` | true | Lower taker/maker |
| `TAKE_PROFIT_PCT` | 0.60–0.80 | More room after fees |
| `STOP_LOSS_PCT` | 0.20–0.25 | Still keep R ≥ 2 |
| `MAX_TRADES_PER_HOUR` | 6–8 | Less fee churn |
| `MIN_HOLD_SECONDS` | 120+ | Avoid instant round-trips |
| `COMPOUND_FRACTION` | 0.7–0.85 | Redeploy wins slowly |
| `TARGET_EQUITY_USDT` | 140 | Soft halt when goal hit |

## What will **not** get you to 150

- More aggressive entry score alone
- Soft paper gates treated as live proof
- Learning from <25 closed trades
- Ignoring maker timeout rate

## Success definition for this desk

First milestone: **fee-net equity 105–110 with controlled DD** over multi-day paper.  
Second: same on testnet.  
Third: mini mainnet.  
140–150 is **compound + time + edge**, not a single code push.
