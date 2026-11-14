# engine_tick

Core per-tick decision path lives in `app/engine_tick.py` (loader) + `app/_et_b64/body.z{0,1}`.

## Entry gates (order)
1. Decision / score / sustained / flow
2. Circuit breaker
3. Anti-churn (hourly, cooldown, daily fee)
4. **Session expectancy** — if `n >= EXPECTANCY_MIN_TRADES` and fee-net expectancy < 0 → no new entries
5. Edge (spread + 2×impact + fee + latency vs alpha)
6. Risk / sizing / portfolio

## Exit
TP / SL / trail (peak ratcheted) / wick confirm / `MAX_HOLD_SECONDS` time_stop / min_hold gate on soft exits.

## Not a profit guarantee
See `docs/PROFIT_PATH.md` and `docs/HONEST_LIMITS.md`.
