"""Expectancy helpers for asymmetric reward/risk sizing policy."""
from __future__ import annotations

# Pessimistic extra stop slippage (% of price) by symbol liquidity tier.
_SYMBOL_SLIP_PCT: dict[str, float] = {
    "btcusdt": 0.05,
    "ethusdt": 0.10,
    "solusdt": 0.20,
    "bnbusdt": 0.18,
}


def reward_risk_ratio(*, take_profit_pct: float, stop_loss_pct: float) -> float:
    if stop_loss_pct <= 0:
        return float("inf")
    return take_profit_pct / stop_loss_pct


def pessimistic_slippage_pct(symbol: str | None = None, *, stress: bool = True) -> float:
    """Extra SL slippage for thin books / crash exits (percent points).

    Example: configured STOP_LOSS_PCT=0.35 with SOL stress → ~0.55 effective.
    """
    base = _SYMBOL_SLIP_PCT.get((symbol or "").lower(), 0.12)
    return base * (1.5 if stress else 1.0)


def effective_stop_loss_pct(
    *,
    stop_loss_pct: float,
    extra_slippage_pct: float = 0.0,
    symbol: str | None = None,
    use_pessimistic: bool = False,
) -> float:
    """Stop level after adverse exit slippage (e.g. 0.35 + 0.15 → 0.50)."""
    extra = extra_slippage_pct
    if use_pessimistic:
        extra = max(extra, pessimistic_slippage_pct(symbol, stress=True))
    return max(0.0, stop_loss_pct) + max(0.0, extra)


def breakeven_win_rate(
    *,
    take_profit_pct: float,
    stop_loss_pct: float,
    fee_rate: float = 0.001,
    extra_slippage_pct: float = 0.0,
) -> float:
    """Minimum win rate (0-1) for zero expectancy after round-trip fees (approx)."""
    tp = take_profit_pct / 100.0
    sl = effective_stop_loss_pct(stop_loss_pct=stop_loss_pct, extra_slippage_pct=extra_slippage_pct) / 100.0
    fee = 2.0 * fee_rate
    denom = tp + sl
    if denom <= 0:
        return 1.0
    return max(0.0, min(1.0, (sl + fee) / denom))


def asymmetric_expectancy(
    *,
    win_rate: float,
    take_profit_pct: float,
    stop_loss_pct: float,
    fee_rate: float = 0.001,
    extra_slippage_pct: float = 0.0,
) -> float:
    """Expected return fraction of notional per completed trade (approx)."""
    p = max(0.0, min(1.0, win_rate))
    tp = take_profit_pct / 100.0
    sl = effective_stop_loss_pct(stop_loss_pct=stop_loss_pct, extra_slippage_pct=extra_slippage_pct) / 100.0
    fee = 2.0 * fee_rate
    return p * (tp - fee) - (1.0 - p) * (sl + fee)
