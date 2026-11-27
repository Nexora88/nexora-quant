"""Offline tests. No credentials and no exchange traffic."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import time
from types import SimpleNamespace

import pytest

from app import engine_tick_body
from app.binance_rest import OrderResult
from app.depth_book import DepthBook
from app.live import LiveExecutor
from app.live_execution_evidence import (
    JournalExecutionCosts, MAX_AGE_SECONDS, MIN_PER_SIDE, SpotEvidenceScope, live_audit_blockers,
)
from app.live_reconciliation import LocalAccountSnapshot
from app.storage import PaperStore

SCOPE = SpotEvidenceScope(77, False, "BTCUSDT")
NOW = 1_700_000_000
KEY = "live:btcusdt"


def sample(order_id, side, *, notional=15.0, seen=NOW, scope=SCOPE, **overrides):
    price = 100.05 if side == "buy" else 99.93
    return {
        "event_key": f"live:{'testnet' if scope.testnet else 'mainnet'}:{scope.symbol}:{order_id}",
        "trade": {
            "exchange_order_id": order_id, "side": side,
            "execution_evidence_scope": scope.stamp(), "execution_style": "market",
            "testnet": scope.testnet, "accounting_complete": True, "fee_estimated": False,
            "execution_latency_measured": True, "execution_latency_ms": 45.0,
            "price": price, "quantity": notional / price,
            "decision_mid": 100.0, "notional_usdt": notional,
            "fee_usdt": notional * 0.001, "status": "FILLED",
            "timestamp": datetime.fromtimestamp(seen, timezone.utc).isoformat(),
            **overrides,
        },
    }


def estimate(rows, **kwargs):
    return JournalExecutionCosts(SCOPE, rows).estimate(**{"now": NOW, "notional": 15, "buy_route": "market", **kwargs})


def test_journal_requires_both_routes_and_quotes_size_and_freshness():
    buys = [sample(i + 1, "buy") for i in range(MIN_PER_SIDE)]
    sells = [sample(i + 101, "sell") for i in range(MIN_PER_SIDE)]
    assert not estimate(buys + sells[:-1]).ready
    cost = estimate(buys + sells)
    assert cost.ready
    assert cost.round_trip_shortfall_bps == pytest.approx(12)
    assert cost.round_trip_fee_bps == pytest.approx(20)
    assert cost.p90_response_ms == 45
    assert "binance_uid" not in cost.public_status()
    assert not estimate(buys + sells, buy_route="limit_maker").ready
    assert not estimate(buys + sells, notional=30).ready
    assert not estimate(buys + sells, now=NOW + MAX_AGE_SECONDS).ready


def test_samples_reject_scope_mixing_duplicates_and_invalid_execution_evidence():
    wrong_rows = [
        sample(100, "buy", scope=SpotEvidenceScope(82, False, "BTCUSDT")),
        sample(101, "buy", scope=SpotEvidenceScope(77, True, "BTCUSDT")),
        sample(102, "buy", scope=SpotEvidenceScope(77, False, "ETHUSDT")),
        sample(103, "buy", seen=NOW + 1),
        sample(104, "buy", execution_style="limit_maker"),
        sample(105, "buy", fee_estimated=True),
        sample(106, "buy", decision_mid=float("nan")),
        sample(107, "buy", execution_latency_measured=False),
        sample(108, "buy", status="EXPIRED"),
        sample(109, "buy", execution_evidence_scope=None),
        sample(110, "buy", exchange_trade_id=777),
    ]
    spread_row = sample(1, "buy")
    assert estimate(wrong_rows + [spread_row] * 50).buy_samples == 1
    mismatched = sample(1, "buy", execution_latency_ms=45.1)
    assert estimate([spread_row, mismatched]).buy_samples == 0


class Exchange:
    testnet = False
    order_id = 0
    cash = 100.0
    base = 0.0
    open_list = False

    def account(self):
        return {"uid": 77, "balances": [
            {"asset": "USDT", "free": str(self.cash), "locked": "0"},
            {"asset": "BTC", "free": str(self.base), "locked": "0"},
        ]}

    def open_orders(self, symbol):
        return []

    def open_order_lists(self):
        return [{"symbol": "BTCUSDT"}] if self.open_list else []

    def exchange_info_symbol(self, symbol):
        return {"filters": [
            {"filterType": "LOT_SIZE", "stepSize": "0.0001", "minQty": "0.0001"},
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
            {"filterType": "NOTIONAL", "minNotional": "5"},
        ]}

    def place_market_order(self, *, symbol, side, quantity, quote_order_qty, client_order_id):
        self.order_id += 1
        qty = quote_order_qty / 100 if side == "BUY" else quantity
        quote = qty * 100
        fee = quote * .001
        self.cash += -quote - fee if side == "BUY" else quote - fee
        self.base += qty if side == "BUY" else -qty
        return OrderResult(
            order_id=self.order_id, client_order_id=client_order_id, symbol=symbol,
            side=side, status="FILLED", price=100.0, orig_qty=qty,
            executed_qty=qty, cummulative_quote_qty=quote,
            fills=[{"id": self.order_id, "qty": qty, "price": 100.0, "commission": fee,
                    "commissionAsset": "USDT"}], raw={},
        )


def attached(client, store):
    ex = LiveExecutor(client, symbol="BTCUSDT", fee_rate=0.001)
    ex.cash_usdt = 100.0
    ex.order_lists_reconciled = True
    ex.attach_order_journal(store, KEY, verify_account=True)
    return ex


def test_wrong_approval_account_cannot_bind_journal_or_send_an_order(tmp_path):
    exchange = Exchange()
    with PaperStore(tmp_path / "live.sqlite3", async_writes=False) as store:
        ex = LiveExecutor(exchange, symbol="BTCUSDT", fee_rate=0.001)
        wrong = SpotEvidenceScope(78, False, "BTCUSDT").stamp()["account_binding"]
        with pytest.raises(RuntimeError, match="does not match the Mainnet approval"):
            ex.attach_order_journal(store, KEY, verify_account=True, expected_account_binding=wrong)
        assert ex.execution_evidence_scope is None
        assert exchange.order_id == 0
        assert store.pending_live_order() is None
        correct = SCOPE.stamp()["account_binding"]
        ex.attach_order_journal(store, KEY, verify_account=True, expected_account_binding=correct)
        assert ex.execution_evidence_scope == SCOPE


def test_real_executor_checkpoints_evidence_and_reloads_after_restart(tmp_path):
    exchange = Exchange()
    path = tmp_path / "live.sqlite3"
    with PaperStore(path, async_writes=False) as store:
        ex = attached(exchange, store)
        assert ex.entry_preflight(notional=15, bid=99.9, ask=100, stop_loss_pct=1) is None
        assert ex.buy(notional_usdt=15, price=100.0, reason="offline", decision_mid=99.9)
        assert ex.sell_quantity(quantity=0.15, price=100.0, reason="offline", decision_mid=100.1)
        # Protective/emergency market sells without an observed decision mid
        # must not accidentally generate price-cost evidence.
        assert ex.buy(notional_usdt=15, price=100.0, reason="offline")
        assert ex.sell_all(price=100.0, reason="offline_emergency")
        assert store.pending_live_order() is None
    with PaperStore(path, async_writes=False) as store:
        ex = attached(exchange, store)
        ex.restore(store.load_state(KEY)["account"])
        model = JournalExecutionCosts(ex.execution_evidence_scope, store.list_trades())
        costs = model.estimate(now=time.time(), notional=15, buy_route="market")
        assert costs.buy_samples == costs.sell_samples == 1
        assert not costs.ready
        assert len(store.list_trades()) == 4


def test_preflight_enforces_protection_floor_and_does_not_overwrite_audited_cash(tmp_path):
    exchange = Exchange()
    with PaperStore(tmp_path / "live.sqlite3", async_writes=False) as store:
        ex = attached(exchange, store)
        assert ex.entry_preflight(
            notional=5, bid=99.9, ask=100, stop_loss_pct=1,
        ) == "protection_notional_below_exchange_floor"
        exchange.cash += 1
        assert ex.entry_preflight(
            notional=15, bid=99.9, ask=100, stop_loss_pct=1,
        ) == "entry_exchange_balance_changed"
        assert ex.cash_usdt == 100
        exchange.cash = 100
        exchange.open_list = True
        assert ex.entry_preflight(
            notional=15, bid=99.9, ask=100, stop_loss_pct=1,
        ) == "entry_unexpected_open_orders"
        assert exchange.order_id == 0


def test_audit_cannot_authorize_a_new_revision(tmp_path):
    with PaperStore(tmp_path / "live.sqlite3", async_writes=False) as store:
        ex = attached(Exchange(), store)
        state = SimpleNamespace(
            exchange_reconciliation={"status": "pass"}, exchange_reconciled_at_monotonic=100,
            exchange_reconciliation_max_age_seconds=30,
            exchange_reconciled_revision=LocalAccountSnapshot.revision(ex),
        )
        assert live_audit_blockers(state, ex, now=110) == []
        assert ex.buy(notional_usdt=15, price=100.0, reason="offline", decision_mid=99.9)
        assert live_audit_blockers(state, ex, now=110) == ["exchange_reconciliation_revision_changed"]
        assert live_audit_blockers(state, ex, now=131) == ["exchange_reconciliation_unavailable_or_stale"]


@pytest.mark.parametrize(("symbol", "testnet"), [("btcusdt", False), ("ethusdt", True)])
def test_mismatched_network_or_symbol_invalidates_live_tick(monkeypatch, symbol, testnet):
    monkeypatch.setattr(
        engine_tick_body, "settings", replace(engine_tick_body.settings, symbol="btcusdt", binance_testnet=True),
    )
    state = engine_tick_body.state
    monkeypatch.setattr(state, "last_message_at", datetime.now(timezone.utc))
    monkeypatch.setattr(state, "latest_depth", object())
    monkeypatch.setattr(state, "last_entry_eligible", True)
    monkeypatch.setattr(state, "last_error", None)
    book = DepthBook(symbol=symbol)
    book.load_snapshot(last_update_id=1, bids=[(99, 2)], asks=[(100, 1)])
    depth = book.publish(
        received_at_ns=time.time_ns(), received_monotonic_ns=time.monotonic_ns(), testnet=testnet,
    )
    result = asyncio.run(engine_tick_body.handle_tick(depth, None, None, None, "live", KEY, None, 4, 23))
    assert result == (0, 23)
    assert state.last_error == "live_depth_network_or_symbol_mismatch"
    assert not state.last_entry_eligible
    assert state.latest_depth is None
