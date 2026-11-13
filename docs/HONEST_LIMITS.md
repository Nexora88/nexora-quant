# Honest limits (retail Nexora Quant)

## What this bot is

- Binance **Spot** L2 microstructure desk (paper / small live).
- Alpha thesis: short-horizon order-flow persistence — **not** co-located HFT.
- Fee-aware: if round-trip costs exceed expected alpha, **no trade** (feature).

## Structural reality (read this before depositing)

### 1. Spot + retail fees + L2 scalp is a hostile equation

VIP0 taker/taker round-trip is typically **~15–20 bps** (more without BNB discount).
Microstructure signals (OBI, micro-price) often live in the **1–5 bps** range.
**Math:** edge.py will correctly refuse most entries. Days with zero trades are
expected, not a bug.

### 2. This is not HFT

Python + home/VPS latency cannot compete with co-located market makers
(Wintermute, Jump, etc.). Spoof/whale filters are **research heuristics**, not
a speed race. Do not frame this as "poor man's HFT."

### 3. Over-filtering paralysis

Many blockers (adverse, flow, churn, edge, risk) stack. That protects capital
but can turn the bot into a **log writer**. Paper soft-gates exist to allow
learning trades; **live must keep full gates**.

### 4. OnlineLearner needs sample size

Adapting gates from fewer than **25 closed trades** is noise-fitting.
Default `LEARNER_MIN_TRADES=25`. Prefer `LEARNER_FROZEN=true` until you have
real closed-trade history. Small accounts open few trades — learner stays cold.

### 5. Paper is not live

Paper fills do not move the book or trigger adverse selection. Live taker
flow is visible; slippage and queue priority are worse. Expect paper edge to
**shrink** on mainnet.

## What success looks like here

| Goal | Realistic? |
|------|------------|
| Don't blow up on fees/churn | Yes — primary design goal |
| Fee-net positive on selective trades | Possible, not guaranteed |
| Passive income / king of finance | No — wrong battlefield |
| Compete with prop HFT on L2 | No |

## Not in this repo (and why)

1. Co-located / native L2 path — separate infrastructure project.
2. Full Futures + margin — different risk class; funding-as-filter may come later.
3. Cross-exchange lead-lag — multi-venue ops cost.
4. Guaranteed maker queue priority — exchange-side; we only price maker fees in math.

## Practical levers that actually help

1. BNB fee discount + VIP if volume allows (`FEE_USE_BNB_DISCOUNT`, `FEE_VIP_LEVEL`).
2. Prefer maker in fee math (`PREFER_MAKER=true`) — still not real queue priority.
3. Fewer quality edges — keep anti-churn; do not lower edge floor on live.
4. 48h+ paper with fee-net log before any live key.
5. Capital discipline — cycling 100→~400→withdraw is coherent with not becoming exit liquidity.

## Go-live order

1. Paper 48h+, fee-net expectancy documented (`retail_reality` on `/status`).
2. Learner frozen or >=25 closed trades reviewed.
3. Testnet → tiny mainnet notional (withdrawals off).
4. VPS only after that — latency is secondary to fee discipline.

## Code pointer

`app/retail_reality.py` — fee wall + posture report for status API.
