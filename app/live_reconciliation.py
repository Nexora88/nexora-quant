"""Fail-closed Binance Spot order, fill, commission and open-order reconciliation.

The exchange is the source of truth for fills. Local records are matched by
exchange order ID; any gap or unpriced commission blocks live trading.
"""
from __future__ import annotations

import asyncio
import math
from copy import deepcopy
from dataclasses import dataclass
import time
from typing import Any, Callable, Iterable, Mapping


def live_trade_event_key(executor: Any, trade: Mapping[str, Any]) -> str:
    """One key for an aggregate order, or one for each individual OCO fill."""
    venue = "testnet" if executor.client.testnet else "mainnet"
    order_id = int(trade.get("exchange_order_id") or 0)
    if order_id <= 0:
        raise ValueError("live ledger entry requires a positive exchange order ID")
    key = f"live:{venue}:{executor.symbol.upper()}:{order_id}"
    trade_id = trade.get("exchange_trade_id")
    if trade_id is not None:
        # Binance trade IDs can start at zero.
        fill_id = int(trade_id)
        if fill_id < 0:
            raise ValueError("live ledger entry has an invalid exchange trade ID")
        key += f":trade:{fill_id}"
    return key


@dataclass(frozen=True, slots=True)
class LocalAccountSnapshot:
    """Copy executor state on the engine thread before starting network I/O."""

    symbol: str
    quote_asset: str
    base_asset: str
    cash_usdt: float
    base_quantity: float
    fees_paid_usdt: float
    protective_order_list_id: int | None
    trades: tuple[dict[str, Any], ...]

    @classmethod
    def capture(cls, executor: Any) -> LocalAccountSnapshot:
        return cls(
            executor.symbol, executor.quote_asset, executor.base_asset, executor.cash_usdt,
            executor.base_quantity, executor.fees_paid_usdt, executor.protective_order_list_id,
            tuple(deepcopy(executor.trades)),
        )

    @staticmethod
    def revision(executor: Any) -> tuple:
        last = executor.trades[-1] if executor.trades else {}
        return (
            executor.symbol, executor.cash_usdt, executor.base_quantity, executor.fees_paid_usdt,
            executor.protective_order_list_id, len(executor.trades),
            last.get("exchange_order_id"), last.get("exchange_trade_id"),
        )


def load_local_trade_ledger(store: Any) -> list[dict[str, Any]]:
    """Read every persisted local trade row, not only the latest dashboard page."""
    rows: list[dict[str, Any]] = []
    before_id: int | None = None
    while True:
        batch = store.list_trades(limit=1000, before_id=before_id)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 1000:
            break
        next_before = min(int(row["id"]) for row in batch)
        if before_id is not None and next_before >= before_id:
            raise RuntimeError("Local trade ledger pagination did not advance")
        before_id = next_before
    return rows


def audit_exchange_history(
    *,
    symbol: str,
    quote_asset: str,
    base_asset: str,
    local_cash: float,
    exchange_cash: float,
    local_base: float,
    exchange_base: float,
    local_fees_usdt: float,
    expected_oco_list_id: int | None,
    local_trade_rows: Iterable[Mapping[str, Any]],
    executor_trades: Iterable[Mapping[str, Any]],
    exchange_orders: Iterable[Mapping[str, Any]],
    exchange_trades: Iterable[Mapping[str, Any]],
    open_orders: Iterable[Mapping[str, Any]],
    open_order_lists: Iterable[Mapping[str, Any]],
    ticker_price: Callable[[str], float],
) -> dict[str, Any]:
    """Build comparable snapshots. Never silently estimates an unknown fee asset."""
    symbol = symbol.upper()
    quote_asset = quote_asset.upper()
    base_asset = base_asset.upper()

    local_items: list[Mapping[str, Any]] = []
    for row in local_trade_rows:
        item = row.get("trade", row)
        if isinstance(item, Mapping):
            local_items.append(item)
    local_items.extend(item for item in executor_trades if isinstance(item, Mapping))

    local_by_fill_key: dict[tuple[int, int | None], Mapping[str, Any]] = {}
    for item in local_items:
        raw_id = item.get("exchange_order_id")
        if raw_id is not None:
            order_id = int(raw_id)
            if order_id > 0:
                raw_trade_id = item.get("exchange_trade_id")
                trade_id = int(raw_trade_id) if raw_trade_id is not None else None
                local_by_fill_key[(order_id, trade_id)] = item
    local_order_ids = {order_id for order_id, _ in local_by_fill_key}
    local_fill_ids = {
        (order_id, trade_id)
        for order_id, trade_id in local_by_fill_key
        if trade_id is not None
    }
    tracked_fill_orders = {order_id for order_id, _ in local_fill_ids}
    if any((order_id, None) in local_by_fill_key for order_id in tracked_fill_orders):
        raise RuntimeError("Live ledger has both aggregate and individual fills for one order")

    local_fee_by_asset: dict[str, float] = {}
    local_fee_usdt_by_asset: dict[str, float] = {}
    local_incomplete_commissions = 0
    for item in local_by_fill_key.values():
        if item.get("accounting_complete") is False or item.get("fee_estimated") is True:
            local_incomplete_commissions += 1
        for asset, amount in (item.get("commission_by_asset") or {}).items():
            key = str(asset).upper()
            local_fee_by_asset[key] = local_fee_by_asset.get(key, 0.0) + float(amount)
        for asset, amount in (item.get("commission_usdt_by_asset") or {}).items():
            key = str(asset).upper()
            local_fee_usdt_by_asset[key] = local_fee_usdt_by_asset.get(key, 0.0) + float(amount)

    order_rows = [item for item in exchange_orders if str(item.get("symbol", symbol)).upper() == symbol]
    exchange_order_ids = {int(item.get("orderId", 0)) for item in order_rows if int(item.get("orderId", 0)) > 0}

    trade_rows = [item for item in exchange_trades if str(item.get("symbol", symbol)).upper() == symbol]
    seen_trade_ids: set[str] = set()
    unique_trades: list[Mapping[str, Any]] = []
    for item in trade_rows:
        trade_id = str(item.get("id", ""))
        if not trade_id:
            raise RuntimeError("Exchange fill is missing its trade ID")
        if trade_id in seen_trade_ids:
            continue
        seen_trade_ids.add(trade_id)
        unique_trades.append(item)

    filled_order_ids = {int(item.get("orderId", 0)) for item in unique_trades}
    if not filled_order_ids <= exchange_order_ids:
        raise RuntimeError("Binance myTrades contains fills absent from allOrders history")

    exchange_fill_ids = {(int(item["orderId"]), int(item["id"])) for item in unique_trades}
    missing_local_fills = {
        key for key in exchange_fill_ids - local_fill_ids if key[0] in tracked_fill_orders
    }
    missing_exchange_fills = local_fill_ids - exchange_fill_ids
    # A known order without a matching trade is not evidence that a local fill occurred.
    missing_local = (filled_order_ids - local_order_ids) | {key[0] for key in missing_local_fills}
    missing_exchange = (local_order_ids - filled_order_ids) | {key[0] for key in missing_exchange_fills}

    exchange_fees_usdt = 0.0
    unpriced_commissions = 0
    fee_by_asset: dict[str, float] = {}
    fee_asset_prices: dict[str, float] = {}
    for fill in unique_trades:
        asset = str(fill.get("commissionAsset", "")).upper()
        amount = float(fill.get("commission", 0) or 0)
        if amount < 0 or not math.isfinite(amount):
            raise RuntimeError("Exchange returned an invalid commission")
        if amount == 0:
            continue
        if not asset:
            unpriced_commissions += 1
            continue
        fee_by_asset[asset] = fee_by_asset.get(asset, 0.0) + amount
        if asset == quote_asset:
            exchange_fees_usdt += amount
        elif asset == base_asset:
            exchange_fees_usdt += amount * float(fill.get("price", 0) or 0)
        else:
            # Historical BNB/third-asset fees must use the local execution-time
            # valuation, not today's ticker. Missing valuation fails closed.
            local_amount = local_fee_by_asset.get(asset, 0.0)
            local_value = local_fee_usdt_by_asset.get(asset, 0.0)
            if local_amount <= 0 or local_value <= 0:
                unpriced_commissions += 1
            else:
                unit_value = local_value / local_amount
                fee_asset_prices[asset] = unit_value
                exchange_fees_usdt += amount * unit_value

    fee_asset_mismatch_count = 0
    for asset in set(local_fee_by_asset) | set(fee_by_asset):
        local_amount = local_fee_by_asset.get(asset, 0.0)
        exchange_amount = fee_by_asset.get(asset, 0.0)
        tolerance = max(1e-10, max(abs(local_amount), abs(exchange_amount)) * 1e-6)
        if abs(local_amount - exchange_amount) > tolerance:
            fee_asset_mismatch_count += 1

    child_order_ids: set[int] = set()
    active_lists: list[Mapping[str, Any]] = []
    for order_list in open_order_lists:
        if str(order_list.get("symbol", symbol)).upper() != symbol:
            continue
        status = str(order_list.get("listStatusType", ""))
        if status in {"EXEC_STARTED", "EXECUTING"}:
            active_lists.append(order_list)
        for child in order_list.get("orderReports", []) or []:
            if int(child.get("orderId", 0) or 0) > 0:
                child_order_ids.add(int(child["orderId"]))
        for child in order_list.get("orders", []) or []:
            if int(child.get("orderId", 0) or 0) > 0:
                child_order_ids.add(int(child["orderId"]))

    unknown_open_orders = [
        item for item in open_orders
        if str(item.get("symbol", symbol)).upper() == symbol
        and int(item.get("orderId", 0) or 0) not in child_order_ids
    ]
    unexpected_active_lists = [
        item for item in active_lists
        if expected_oco_list_id is None
        or int(item.get("orderListId", 0) or 0) != int(expected_oco_list_id)
    ]
    expected_open_list_count = 1 if expected_oco_list_id is not None else 0

    local = {
        "cash_usdt": float(local_cash),
        "base_quantity": float(local_base),
        "fees_usdt": float(local_fees_usdt),
        "open_order_count": expected_open_list_count,
        "unmatched_exchange_order_count": 0,
        "unmatched_local_order_count": 0,
        "unknown_open_order_count": 0,
        "unpriced_commission_count": local_incomplete_commissions,
        "fee_asset_mismatch_count": 0,
    }
    exchange = {
        "cash_usdt": float(exchange_cash),
        "base_quantity": float(exchange_base),
        "fees_usdt": exchange_fees_usdt,
        "open_order_count": len(active_lists),
        "unmatched_exchange_order_count": len(missing_local),
        "unmatched_local_order_count": len(missing_exchange),
        "unknown_open_order_count": len(unknown_open_orders) + len(unexpected_active_lists),
        "unpriced_commission_count": unpriced_commissions,
        "fee_asset_mismatch_count": fee_asset_mismatch_count,
    }
    return {
        "local": local,
        "exchange": exchange,
        "details": {
            "symbol": symbol,
            "exchange_order_count": len(order_rows),
            "exchange_fill_count": len(unique_trades),
            "local_order_count": len(local_order_ids),
            "exchange_fee_by_asset": fee_by_asset,
            "local_fee_by_asset": local_fee_by_asset,
            "historical_fee_asset_usdt_unit_values": fee_asset_prices,
            "missing_local_order_ids": sorted(missing_local),
            "missing_exchange_order_ids": sorted(missing_exchange),
            "missing_local_fill_ids": [list(key) for key in sorted(missing_local_fills)],
            "missing_exchange_fill_ids": [list(key) for key in sorted(missing_exchange_fills)],
            "unknown_open_order_ids": sorted(
                int(item.get("orderId", 0) or 0) for item in unknown_open_orders
            ),
            "unexpected_active_order_list_ids": sorted(
                int(item.get("orderListId", 0) or 0) for item in unexpected_active_lists
            ),
            "unpriced_commission_count": unpriced_commissions,
        },
    }


def fetch_exchange_audit(
    *,
    client: Any,
    executor: Any,
    local_trade_rows: Iterable[Mapping[str, Any]],
    exchange_orders: Iterable[Mapping[str, Any]] | None = None,
    exchange_trades: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fetch full history when not supplied and reconcile current open-order state."""
    symbol = executor.symbol
    orders = list(exchange_orders) if exchange_orders is not None else client.all_orders(symbol, from_id=0)
    trades = list(exchange_trades) if exchange_trades is not None else client.all_my_trades(symbol, from_id=0)
    account = client.account()
    balances = {str(item.get("asset", "")).upper(): item for item in account.get("balances", [])}
    quote = balances.get(executor.quote_asset, {})
    base = balances.get(executor.base_asset, {})
    return audit_exchange_history(
        symbol=symbol,
        quote_asset=executor.quote_asset,
        base_asset=executor.base_asset,
        local_cash=executor.cash_usdt,
        exchange_cash=float(quote.get("free", 0) or 0),
        local_base=executor.base_quantity,
        exchange_base=float(base.get("free", 0) or 0) + float(base.get("locked", 0) or 0),
        local_fees_usdt=executor.fees_paid_usdt,
        expected_oco_list_id=executor.protective_order_list_id,
        local_trade_rows=local_trade_rows,
        executor_trades=executor.trades,
        exchange_orders=orders,
        exchange_trades=trades,
        open_orders=client.open_orders(symbol),
        open_order_lists=client.open_order_lists(),
        ticker_price=client.ticker_price,
    )


class RecurringExchangeAudit:
    """Reuse history only for an unchanged local revision, with a fresh check on drift."""

    def __init__(self, interval_seconds: float) -> None:
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("history refresh interval must be finite and positive")
        self.interval_seconds = interval_seconds
        self._cache: tuple[tuple, float, list, list] | None = None

    def read(
        self, *, client: Any, snapshot: LocalAccountSnapshot, local_trade_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from app.dual_account import reconciliation_differences

        revision = LocalAccountSnapshot.revision(snapshot)
        if self._cache is not None:
            cached_revision, cached_at, orders, trades = self._cache
            if revision == cached_revision and time.monotonic() - cached_at < self.interval_seconds:
                result = fetch_exchange_audit(
                    client=client, executor=snapshot, local_trade_rows=local_trade_rows,
                    exchange_orders=orders, exchange_trades=trades,
                )
                if not reconciliation_differences(result["local"], result["exchange"]):
                    result["details"]["history_refreshed"] = False
                    return result
        self._cache = None
        orders = client.all_orders(snapshot.symbol, from_id=0)
        trades = client.all_my_trades(snapshot.symbol, from_id=0)
        result = fetch_exchange_audit(
            client=client, executor=snapshot, local_trade_rows=local_trade_rows,
            exchange_orders=orders, exchange_trades=trades,
        )
        self._cache = (revision, time.monotonic(), orders, trades)
        result["details"]["history_refreshed"] = True
        return result


async def read_stable_exchange_audit(
    *, executor: Any, store: Any, audit: RecurringExchangeAudit,
) -> dict[str, Any]:
    """Retry if the engine changes the local snapshot while REST is in flight."""
    client = executor.client

    def read(snapshot: LocalAccountSnapshot) -> dict[str, Any]:
        return audit.read(
            client=client, snapshot=snapshot, local_trade_rows=load_local_trade_ledger(store),
        )

    for _ in range(3):
        snapshot = LocalAccountSnapshot.capture(executor)
        revision = LocalAccountSnapshot.revision(snapshot)
        try:
            result = await asyncio.to_thread(read, snapshot)
        except Exception:
            if LocalAccountSnapshot.revision(executor) != revision:
                continue
            raise
        if LocalAccountSnapshot.revision(executor) == revision:
            return result
    raise RuntimeError("Local account changed during consecutive reconciliation reads")
