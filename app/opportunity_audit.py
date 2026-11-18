"""Post-hoc audit of blocked entry candidates using only later executable quotes.

This is research telemetry, never an entry signal. Each candidate is marked at
its ask and evaluated at the first quote at/after each horizon. Fees and
per-side slippage are charged on both legs. Missing/stale future quotes remain
unevaluated rather than being filled with a convenient price.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from statistics import median
from typing import Any, Iterable


def audit_blocked_candidates(
    candidates: Iterable[dict[str, Any]],
    quotes: Iterable[dict[str, Any]],
    *,
    horizons_seconds: tuple[int, ...] = (30, 60, 300),
    fee_rate: float = 0.001,
    slippage_bps_per_side: float = 3.0,
    max_quote_delay_seconds: float = 2.0,
) -> dict[str, Any]:
    """Evaluate blocked longs at future bid quotes; does not alter trading decisions.

    Candidate fields: timestamp_ns, entry_ask, blockers (list[str]).
    Quote fields: timestamp_ns, bid, ask. Quotes must be from the same symbol.
    A horizon is evaluated only when a valid quote exists no more than
    max_quote_delay_seconds after the target time.
    """
    if not 0 <= fee_rate < 0.1:
        raise ValueError("fee_rate must be in [0, 0.1)")
    if slippage_bps_per_side < 0 or max_quote_delay_seconds < 0:
        raise ValueError("slippage and quote delay must be non-negative")
    if not horizons_seconds or any(
        isinstance(h, bool) or not isinstance(h, int) or h <= 0 for h in horizons_seconds
    ):
        raise ValueError("horizons_seconds must contain positive integers")

    ordered_quotes = sorted(
        (
            (int(q["timestamp_ns"]), float(q["bid"]), float(q["ask"]))
            for q in quotes
            if float(q.get("bid", 0)) > 0 and float(q.get("ask", 0)) >= float(q.get("bid", 0))
        ),
        key=lambda row: row[0],
    )
    quote_times = [row[0] for row in ordered_quotes]
    slip = slippage_bps_per_side / 10_000.0
    buy_cost_factor = (1.0 + slip) * (1.0 + fee_rate)
    sell_proceeds_factor = (1.0 - slip) * (1.0 - fee_rate)
    max_delay_ns = int(max_quote_delay_seconds * 1_000_000_000)

    outcomes: list[dict[str, Any]] = []
    by_horizon: dict[str, list[float]] = {str(h): [] for h in horizons_seconds}
    by_blocker: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {str(h): [] for h in horizons_seconds}
    )

    for candidate in candidates:
        ts = int(candidate["timestamp_ns"])
        entry_ask = float(candidate["entry_ask"])
        if ts < 0 or entry_ask <= 0:
            raise ValueError("candidate timestamp and entry ask must be positive")
        blockers = sorted({str(x) for x in candidate.get("blockers", []) if str(x)})
        if not blockers:
            continue
        candidate_result: dict[str, Any] = {
            "timestamp_ns": ts,
            "entry_ask": entry_ask,
            "blockers": blockers,
            "net_return_bps": {},
        }
        for horizon in horizons_seconds:
            key = str(horizon)
            target = ts + horizon * 1_000_000_000
            idx = bisect_left(quote_times, target)
            if idx >= len(ordered_quotes):
                candidate_result["net_return_bps"][key] = None
                continue
            quote_ts, future_bid, _future_ask = ordered_quotes[idx]
            if quote_ts <= ts or quote_ts - target > max_delay_ns:
                candidate_result["net_return_bps"][key] = None
                continue
            net_return = (
                future_bid * sell_proceeds_factor / (entry_ask * buy_cost_factor) - 1.0
            ) * 10_000.0
            candidate_result["net_return_bps"][key] = net_return
            by_horizon[key].append(net_return)
            for blocker in blockers:
                by_blocker[blocker][key].append(net_return)
        outcomes.append(candidate_result)

    def summarize(values: list[float]) -> dict[str, Any]:
        return {
            "evaluated": len(values),
            "positive_net_pct": (sum(v > 0 for v in values) / len(values) * 100.0)
            if values else None,
            "mean_net_bps": sum(values) / len(values) if values else None,
            "median_net_bps": median(values) if values else None,
        }

    return {
        "candidate_count": len(outcomes),
        "horizons_seconds": list(horizons_seconds),
        "by_horizon": {h: summarize(values) for h, values in by_horizon.items()},
        "by_blocker": {
            blocker: {h: summarize(values) for h, values in horizons.items()}
            for blocker, horizons in sorted(by_blocker.items())
        },
        "outcomes": outcomes,
        "methodology": (
            "Post-hoc only: candidate ask entry, first later bid at/after horizon, "
            "both-side fees and slippage; no future data enters live/replay decisions."
        ),
    }
