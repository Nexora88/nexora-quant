# Quant microstructure layer

## Why simple top-of-book imbalance fails
Public TOB imbalance is heavily competed by co-located HFT. This repo adds
research-grade microstructure features; they do **not** guarantee profit on a
retail internet path against co-located flow.

## Math modules (`app/analytics/`)

### Weighted multi-level OBI
\[
OBI_t = \frac{\sum_i w_i Q^{bid}_{i,t} - \sum_i w_i Q^{ask}_{i,t}}{\sum_i w_i Q^{bid}_{i,t} + \sum_i w_i Q^{ask}_{i,t}}
\]
Weights: harmonic \(w_i=1/i\) or exponential decay.

### Micro-price
\[
P_{micro} = \frac{Q_{bid} P_{ask} + Q_{ask} P_{bid}}{Q_{bid}+Q_{ask}}
\]

### Ornstein–Uhlenbeck z-score on OBI
Rolling mean/variance of OBI; fade extremes when \(|z| > 2\) in **range** regime.

## Regime classifier
Online thresholds on volatility / spread → `trend` | `range` | `stressed`.

## Dynamic Kelly (`app/dynamic_gate.py`)
Half-Kelly fraction from recent PnL win rate and payoff ratio, capped by risk limits.

## Shadow book (`app/shadow.py`)
Three parallel paper parameter sets on the same L2 stream; dashboard shows leaderboard.

## Honesty
Edge is not promised. Use L2 backtests across regimes, small size, testnet first.
