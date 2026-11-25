"""Derive conservative execution-cost floors from the bound live journal."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import math
from typing import Iterable, Mapping, Any

from app.live_reconciliation import LocalAccountSnapshot

MIN_PER_SIDE = 30
MAX_AGE_SECONDS = 7 * 24 * 3600
WINDOW_PER_SIDE = 500


@dataclass(frozen=True, slots=True)
class SpotEvidenceScope:
    binance_uid: int
    testnet: bool
    symbol: str

    def stamp(self) -> dict:
        binding = f"binance-spot|{self.binance_uid}|{self.testnet}|{self.symbol}"
        return {
            "version": 1, "account_binding": sha256(binding.encode()).hexdigest(),
            "testnet": self.testnet, "symbol": self.symbol,
        }


@dataclass(frozen=True, slots=True)
class _Sample:
    order_id: int
    side: str
    seen_at: float
    notional: float
    shortfall_bps: float
    fee_bps: float
    response_ms: float


@dataclass(frozen=True, slots=True)
class CostEvidence:
    buy_samples: int
    sell_samples: int
    required_per_side: int
    buy_route: str
    sell_route: str
    round_trip_shortfall_bps: float | None = None
    round_trip_fee_bps: float | None = None
    p90_response_ms: float | None = None

    @property
    def ready(self) -> bool:
        return self.round_trip_shortfall_bps is not None

    def public_status(self) -> dict:
        return {**asdict(self), "ready": self.ready}


def _p90(values: Iterable[float]) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * 0.90) - 1]


class JournalExecutionCosts:
    """Read only scoped, fee-complete market orders with a directly timed terminal response.

    The response RTT is diagnostic, not an estimate of the matching-engine fill time.
    Paper trades, OCO exits, maker orders and recovered/time-out responses cannot
    populate this version's market-order buckets.
    """

    def __init__(self, scope: SpotEvidenceScope, rows: Iterable[Mapping[str, Any]]) -> None:
        expected_scope = scope.stamp()
        samples: dict[int, _Sample] = {}
        conflicted: set[int] = set()
        network = "testnet" if scope.testnet else "mainnet"
        for row in rows:
            try:
                trade = row["trade"]
                order_id = trade["exchange_order_id"]
                side = trade["side"]
                measured_scope = trade.get("execution_evidence_scope")
                if (
                    not isinstance(measured_scope, dict) or measured_scope != expected_scope
                    or measured_scope.get("testnet") is not scope.testnet
                    or type(order_id) is not int or order_id <= 0
                    or row["event_key"] != f"live:{network}:{scope.symbol}:{order_id}"
                    or trade.get("testnet") is not scope.testnet or side not in {"buy", "sell"}
                    or trade.get("execution_style") != "market"
                    or trade.get("execution_latency_measured") is not True
                    or trade.get("accounting_complete") is not True or trade.get("fee_estimated") is not False
                    or trade.get("status") != "FILLED" or trade.get("exchange_trade_id") is not None
                ):
                    continue
                timestamp = datetime.fromisoformat(trade["timestamp"])
                if timestamp.tzinfo is None:
                    continue
                mid = float(trade["decision_mid"])
                fill_price = float(trade["price"])
                qty = float(trade["quantity"])
                notional = float(trade["notional_usdt"])
                response_ms = float(trade["execution_latency_ms"])
                fee = float(trade["fee_usdt"])
                if (
                    not all(math.isfinite(v) and v > 0 for v in (mid, fill_price, qty, notional, response_ms))
                    or not math.isclose(fill_price * qty, notional, rel_tol=1e-9, abs_tol=1e-8)
                    or not math.isfinite(fee) or fee < 0
                ):
                    continue
                signed_move = fill_price - mid if side == "buy" else mid - fill_price
                shortfall_bps = max(0.0, (signed_move / mid) * 10_000)
                if not math.isfinite(shortfall_bps):
                    continue
                fee_bps = (fee / notional) * 10_000
                if not math.isfinite(fee_bps):
                    continue
                sample = _Sample(order_id, side, timestamp.timestamp(), notional, shortfall_bps, fee_bps, response_ms)
                if order_id in samples and samples[order_id] != sample:
                    conflicted.add(order_id)
                samples[order_id] = sample
            except (AttributeError, TypeError, ValueError, KeyError, OverflowError, OSError):
                # Legacy/incomplete rows still belong in the accounting ledger,
                # but never become execution calibration evidence.
                continue
        self._samples = tuple(
            sorted((x for id_, x in samples.items() if id_ not in conflicted),
                   key=lambda x: (x.seen_at, x.order_id), reverse=True)
        )

    def estimate(self, *, now: float, notional: float, buy_route: str) -> CostEvidence:
        if not (math.isfinite(now) and math.isfinite(notional) and notional > 0):
            raise ValueError("Execution estimate requires a finite time and positive notional")
        by_side: dict[str, list[_Sample]] = {"buy": [], "sell": []}
        for sample in self._samples:
            if now - sample.seen_at >= MAX_AGE_SECONDS:
                break
            if all(len(group) >= WINDOW_PER_SIDE for group in by_side.values()):
                break
            group = by_side[sample.side]
            if (
                len(group) < WINDOW_PER_SIDE
                and 0 <= now - sample.seen_at < MAX_AGE_SECONDS
                and 0.80 * notional <= sample.notional <= 1.25 * notional
            ):
                group.append(sample)
        buy = by_side["buy"] if buy_route == "market" else []
        sell = by_side["sell"]
        if min(len(buy), len(sell)) < MIN_PER_SIDE:
            return CostEvidence(len(buy), len(sell), MIN_PER_SIDE, buy_route, "market")
        return CostEvidence(
            len(buy), len(sell), MIN_PER_SIDE, buy_route, "market",
            _p90(x.shortfall_bps for x in buy) + _p90(x.shortfall_bps for x in sell),
            _p90(x.fee_bps for x in buy) + _p90(x.fee_bps for x in sell),
            max(_p90(x.response_ms for x in buy), _p90(x.response_ms for x in sell)),
        )


def live_audit_blockers(state: Any, executor: Any, *, now: float) -> list[str]:
    """The same audit revision and freshness guard used by readiness and order entry."""
    checked_at = getattr(state, "exchange_reconciled_at_monotonic", None)
    blockers: list[str] = []
    if (
        getattr(state, "exchange_reconciliation", {}).get("status") != "pass"
        or checked_at is None
        or not 0 <= now - checked_at <= state.exchange_reconciliation_max_age_seconds
    ):
        blockers.append("exchange_reconciliation_unavailable_or_stale")
    elif executor is not None and (
        getattr(state, "exchange_reconciled_revision", None) != LocalAccountSnapshot.revision(executor)
    ):
        blockers.append("exchange_reconciliation_revision_changed")
    if getattr(executor, "order_state_uncertain", False):
        blockers.append("order_state_uncertain")
    if not getattr(executor, "order_lists_reconciled", False):
        blockers.append("order_lists_unreconciled")
    return blockers
