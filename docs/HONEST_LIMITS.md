# Honest limits (retail Spot L2 desk)

This is not a profit guarantee. Edge-absent ticks open zero trades by design.

## Fee wall

Spot VIP0 taker ~10 bps each way. Scalp TP 40–90 bps leaves a thin net band after
round-trip fee + spread + impact. Maker entry improves the math; it does not
erase the wall.

## What "ready" means here

1. Paper: fee-net expectancy > 0 over enough closed trades (not one lucky fill).
2. `scripts/go_live_gate.py` stamp present when `REQUIRE_GO_LIVE_GATE=true`.
3. Max drawdown and daily loss limits never disabled for live.
4. VPS only after that — latency is secondary to fee discipline.

## Code pointer

`app/retail_reality.py` — fee wall + posture report for status API.

## Maker entry / taker exit (accepted)

- **Entry** with `PREFER_MAKER=true` uses post-only LIMIT_MAKER (live) or bid-side paper fill.
  Fee edge improves; timeout/cancel is intentional (no market fallback that tick).
- **Exit** on TP uses exchange OCO limit when installed. Trail / time_stop / emergency
  flatten remain **taker** (`sell_quantity` market). Commission budget must assume
  maker-in + often-taker-out, not pure maker-maker round-trip.
- Paper maker fill walks `depth_bids` as liquidity; may slightly overstate slippage vs
  true passive fill. Direction is conservative (worse), not optimistic.
- Watch `/status` → `maker_stats.timeout_rate`. Sustained >30% ⇒ maker path is weak
  in that regime; edge math still assumes maker fee only when fill actually tags maker.
