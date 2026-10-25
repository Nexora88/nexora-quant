"""Order-book microstructure math: weighted OBI, micro-price, OU mean-reversion.

These are descriptive research features. They do not guarantee edge; HFT latency
and adverse selection can erase TOB-style signals on public internet paths.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import exp, sqrt
from typing import Iterable, Sequence


def _levels(
    side: Iterable[tuple[float, float]] | Sequence[tuple[float, float]],
    n: int,
) -> list[tuple[float, float]]:
    rows: list[tuple[float, float]] = []
    for i, row in enumerate(side):
        if i >= n:
            break
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        price, qty = float(row[0]), float(row[1])
        if price > 0 and qty > 0:
            rows.append((price, qty))
    return rows


def decay_weights(n: int, *, scheme: str = "harmonic", alpha: float = 0.35) -> list[float]:
    if n < 1:
        raise ValueError("n must be >= 1")
    if scheme == "harmonic":
        return [1.0 / i for i in range(1, n + 1)]
    if scheme == "exp":
        return [exp(-alpha * i) for i in range(n)]
    raise ValueError("scheme must be 'harmonic' or 'exp'")


def calculate_weighted_obi(
    bids: Sequence[tuple[float, float]] | Iterable[tuple[float, float]],
    asks: Sequence[tuple[float, float]] | Iterable[tuple[float, float]],
    *,
    levels: int = 10,
    scheme: str = "harmonic",
    alpha: float = 0.35,
) -> float | None:
    """Multi-level volume-weighted order book imbalance in [-1, 1]."""
    if levels < 1:
        raise ValueError("levels must be >= 1")
    bid_lv = _levels(bids, levels)
    ask_lv = _levels(asks, levels)
    if not bid_lv or not ask_lv:
        return None
    n = max(len(bid_lv), len(ask_lv))
    weights = decay_weights(n, scheme=scheme, alpha=alpha)
    bid_w = sum(weights[i] * bid_lv[i][1] for i in range(len(bid_lv)))
    ask_w = sum(weights[i] * ask_lv[i][1] for i in range(len(ask_lv)))
    total = bid_w + ask_w
    if total <= 0:
        return None
    return (bid_w - ask_w) / total


def calculate_micro_price(
    *,
    bid: float,
    ask: float,
    bid_qty: float,
    ask_qty: float,
) -> float | None:
    """Liquidity-weighted micro-price: (Qb*Pa + Qa*Pb) / (Qb + Qa)."""
    if bid <= 0 or ask < bid or bid_qty < 0 or ask_qty < 0:
        return None
    total = bid_qty + ask_qty
    if total <= 0:
        return None
    return (bid_qty * ask + ask_qty * bid) / total


@dataclass(slots=True)
class MicrostructureSnapshot:
    weighted_obi: float | None
    micro_price: float | None
    mid: float
    micro_premium_bps: float
    ou_zscore: float | None
    mean_reversion_signal: str


class OrnsteinUhlenbeckTracker:
    """Track OBI as mean-reverting; emit z-score vs rolling mean."""

    def __init__(self, maxlen: int = 300, z_entry: float = 2.0) -> None:
        if maxlen < 20:
            raise ValueError("maxlen must be >= 20 for stable stats")
        if z_entry <= 0:
            raise ValueError("z_entry must be positive")
        self._x: deque[float] = deque(maxlen=maxlen)
        self.z_entry = z_entry

    def update(self, obi: float | None) -> float | None:
        if obi is None:
            return None
        self._x.append(float(obi))
        return self.zscore()

    def zscore(self) -> float | None:
        if len(self._x) < 30:
            return None
        vals = list(self._x)
        n = len(vals)
        mu = sum(vals) / n
        var = sum((v - mu) ** 2 for v in vals) / max(1, n - 1)
        sigma = sqrt(var) if var > 0 else 0.0
        if sigma <= 1e-12:
            return 0.0
        return (vals[-1] - mu) / sigma

    def theta_proxy(self) -> float | None:
        if len(self._x) < 40:
            return None
        vals = list(self._x)
        n = len(vals)
        mu = sum(vals) / n
        num = sum((vals[i] - mu) * (vals[i - 1] - mu) for i in range(1, n))
        den = sum((v - mu) ** 2 for v in vals)
        if den <= 1e-18:
            return None
        rho = num / den
        return max(0.0, min(1.0, 1.0 - abs(rho)))

    def mean_reversion_side(self) -> str:
        z = self.zscore()
        if z is None:
            return "none"
        if z >= self.z_entry:
            return "fade_bid"
        if z <= -self.z_entry:
            return "fade_ask"
        return "none"


def build_snapshot(
    *,
    bid: float,
    ask: float,
    bid_qty: float,
    ask_qty: float,
    bids: Sequence[tuple[float, float]] | None = None,
    asks: Sequence[tuple[float, float]] | None = None,
    ou: OrnsteinUhlenbeckTracker | None = None,
    levels: int = 10,
) -> MicrostructureSnapshot:
    mid = (bid + ask) / 2.0 if bid > 0 and ask >= bid else 0.0
    micro = calculate_micro_price(bid=bid, ask=ask, bid_qty=bid_qty, ask_qty=ask_qty)
    if bids is not None and asks is not None:
        obi = calculate_weighted_obi(bids, asks, levels=levels)
    else:
        total = bid_qty + ask_qty
        obi = ((bid_qty - ask_qty) / total) if total > 0 else None
    premium = 0.0
    if micro is not None and mid > 0:
        premium = (micro - mid) / mid * 10_000.0
    z = ou.update(obi) if ou is not None else None
    mr = ou.mean_reversion_side() if ou is not None else "none"
    return MicrostructureSnapshot(
        weighted_obi=obi,
        micro_price=micro,
        mid=mid,
        micro_premium_bps=premium,
        ou_zscore=z,
        mean_reversion_signal=mr,
    )
