import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.binance_rest import BinanceRestClient, OrderResult
from app.live import LiveExecutor
from app.live_maker import install_buy_limit
from app.storage import PaperStore, exclusive_live_worker

KEY = "live:btcusdt"


class ProcessExit(BaseException):
    """Simulate process exit without executing application exception handlers."""


class Exchange:
    testnet = True
    uid = 42
    order = None
    posts = 0

    def __init__(self, path):
        self.path = path
        self.place_mode = "ok"
        self.cancel_mode = "ok"

    def account(self):
        return {"uid": self.uid}

    def exchange_info_symbol(self, symbol):
        return {"filters": [{"filterType": "LOT_SIZE", "stepSize": "0.001"}]}

    @staticmethod
    def result(client_id, *, status="FILLED", qty=0.1, side="BUY"):
        return OrderResult(
            order_id=77, client_order_id=client_id, symbol="BTCUSDT",
            side=side, status=status, price=100, orig_qty=0.1,
            executed_qty=qty, cummulative_quote_qty=round(qty * 100, 8), fills=[],
            raw={},
        )

    def place_market_order(self, **params):
        self.posts += 1
        # An independent connection must observe the committed intent at POST.
        with PaperStore(self.path, async_writes=False) as observer:
            assert observer.pending_live_order()["client_id"] == params["client_order_id"]
            assert observer._db.execute("PRAGMA synchronous").fetchone()[0] == 2
        if self.place_mode == "before":
            raise TimeoutError("request may not have reached Binance")
        self.order = self.result(params["client_order_id"], side=params["side"])
        if self.place_mode == "crash":
            raise ProcessExit()
        if self.place_mode == "after":
            raise TimeoutError("accepted but response lost")
        return self.order

    def get_order_by_client_id(self, symbol, client_order_id):
        if self.order is None or self.order.client_order_id != client_order_id:
            raise LookupError("order not found or not yet visible")
        return self.order

    def get_order(self, symbol, order_id):
        assert order_id == 77
        return self.order

    def order_trades(self, symbol, order_id):
        assert order_id == 77
        return [{
            "id": 0, "orderId": 77, "qty": str(self.order.executed_qty), "price": "100",
            "commission": "0.01", "commissionAsset": "USDT", "isBuyer": self.order.side == "BUY",
        }]

    def place_limit_order(self, **params):
        self.posts += 1
        with PaperStore(self.path, async_writes=False) as observer:
            assert observer.pending_live_order()["kind"] == "limit_maker"
        self.order = self.result(params["client_order_id"], status="PARTIALLY_FILLED", qty=0.03)
        return self.order

    def cancel_order(self, *, symbol, order_id):
        with PaperStore(self.path, async_writes=False) as observer:
            assert observer.pending_live_order()["exchange_id"] == order_id
        if self.cancel_mode == "open":
            raise TimeoutError("never canceled")
        qty = 0 if self.cancel_mode == "empty" else 0.07
        self.order = self.result("exchange-renamed-cancel", status="CANCELED", qty=qty)
        if self.cancel_mode == "crash":
            raise ProcessExit()
        raise TimeoutError("canceled with an extra fill before the response was lost")


def executor(exchange, store, *, verify=True):
    ex = LiveExecutor(exchange, symbol="BTCUSDT", fee_rate=0.001)
    saved = store.load_state(KEY)
    if saved:
        ex.restore(saved["account"])
    else:
        ex.starting_cash_usdt = ex.cash_usdt = 100
    ex.attach_order_journal(store, KEY, verify_account=verify)
    return ex


def market(ex):
    return ex.buy(notional_usdt=10, price=100, reason="test")


def maker(ex):
    install_buy_limit(type(ex))
    return ex.buy_limit(notional_usdt=10, limit_price=100, reason="test")


def test_market_accepted_then_crashes_recovers_from_disk_exactly_once(tmp_path):
    path = tmp_path / "live.sqlite3"
    exchange = Exchange(path)
    exchange.place_mode = "crash"
    with PaperStore(path, async_writes=False) as store:
        ex = executor(exchange, store)
        with pytest.raises(ProcessExit):
            market(ex)
        assert store.load_state(KEY)["account"]["base_quantity"] == 0
        assert not store.list_trades()
    with PaperStore(path, async_writes=False) as store:
        recovered = executor(exchange, store)
        assert recovered.reconcile_uncertain_order()
        assert recovered.base_quantity == pytest.approx(0.1)
        assert recovered.cash_usdt == pytest.approx(89.99)
        assert store.pending_live_order() is None
        assert store.load_state(KEY)["uncheckpointed_live_order"] == exchange.order.client_order_id
        assert len(store.list_trades()) == 1
    with PaperStore(path, async_writes=False) as store:
        later = executor(exchange, store)
        assert later.reconcile_uncertain_order()
        assert later.base_quantity == pytest.approx(0.1)
        assert len(store.list_trades()) == 1
    assert exchange.posts == 1


def test_missing_exchange_order_never_retries_even_after_restart(tmp_path):
    path = tmp_path / "live.sqlite3"
    exchange = Exchange(path)
    exchange.place_mode = "before"
    with PaperStore(path, async_writes=False) as store:
        with pytest.raises(LookupError):
            market(executor(exchange, store))
        original = store.pending_live_order()["client_id"]
    with PaperStore(path, async_writes=False) as store:
        recovered = executor(exchange, store)
        assert not recovered.reconcile_uncertain_order()
        assert recovered.unresolved_client_order_id == original
        with pytest.raises(RuntimeError, match="uncertain"):
            market(recovered)
        assert store.pending_live_order()["client_id"] == original
    assert exchange.posts == 1


def test_timeout_after_acceptance_is_not_measured_latency(tmp_path):
    path = tmp_path / "live.sqlite3"
    exchange = Exchange(path)
    exchange.place_mode = "after"
    with PaperStore(path, async_writes=False) as store:
        trade = market(executor(exchange, store))
        assert trade["execution_latency_measured"] is False
        assert store.pending_live_order() is None
        assert len(store.list_trades()) == 1
    assert exchange.posts == 1


def test_maker_uses_final_quantity_including_late_fills(tmp_path):
    path = tmp_path / "live.sqlite3"
    exchange = Exchange(path)
    with PaperStore(path, async_writes=False) as store:
        ex = executor(exchange, store)
        assert maker(ex)["quantity"] == pytest.approx(0.07)
        assert ex.base_quantity == pytest.approx(0.07)
        assert store.pending_live_order() is None
        assert len(store.list_trades()) == 1
    assert exchange.posts == 1


def test_terminal_zero_fill_clears_intent_without_creating_a_trade(tmp_path):
    path = tmp_path / "live.sqlite3"
    exchange = Exchange(path)
    exchange.cancel_mode = "empty"
    with PaperStore(path, async_writes=False) as store:
        assert maker(executor(exchange, store)) is None
        assert store.pending_live_order() is None
        assert not store.list_trades()


@pytest.mark.parametrize("mode", ["open", "crash"])
def test_maker_open_or_crash_never_applies_partial_before_terminal(tmp_path, mode):
    path = tmp_path / "live.sqlite3"
    exchange = Exchange(path)
    exchange.cancel_mode = mode
    with PaperStore(path, async_writes=False) as store:
        ex = executor(exchange, store)
        with pytest.raises(ProcessExit if mode == "crash" else RuntimeError):
            maker(ex)
        intent = store.pending_live_order()
        assert intent["exchange_id"] == 77
        assert ex.base_quantity == 0
        assert not store.list_trades()
    with PaperStore(path, async_writes=False) as store:
        ex = executor(exchange, store)
        if mode == "open":
            assert not ex.reconcile_uncertain_order()
            assert ex.base_quantity == 0
            exchange.order = exchange.result("operator-canceled", status="CANCELED", qty=0.07)
        assert ex.reconcile_uncertain_order()
        assert ex.trades[-1]["client_order_id"] == intent["client_id"]
        assert ex.base_quantity == pytest.approx(0.07)
    assert exchange.posts == 1


def test_positive_cancel_ack_with_open_exchange_status_stays_pending(tmp_path, monkeypatch):
    path = tmp_path / "live.sqlite3"
    exchange = Exchange(path)
    monkeypatch.setattr(exchange, "cancel_order", lambda **kw: {"status": "CANCELED"})
    with PaperStore(path, async_writes=False) as store:
        ex = executor(exchange, store)
        with pytest.raises(RuntimeError, match="not terminal"):
            maker(ex)
        assert ex.order_state_uncertain
        assert store.pending_live_order()
        assert not store.list_trades()


@pytest.mark.parametrize("malformed", ["mismatched", "duplicate", "empty", "wrong_side"])
def test_terminal_order_requires_complete_fills(tmp_path, monkeypatch, malformed):
    path = tmp_path / "live.sqlite3"
    exchange = Exchange(path)
    good_fills = exchange.order_trades

    def fills(*args):
        fill = good_fills(*args)[0]
        return {
            "mismatched": [{**fill, "qty": "0.03"}], "empty": [],
            "duplicate": [fill, fill], "wrong_side": [{**fill, "isBuyer": False}],
        }[malformed]

    monkeypatch.setattr(exchange, "order_trades", fills)
    with PaperStore(path, async_writes=False) as store:
        ex = executor(exchange, store)
        with pytest.raises(RuntimeError, match="fill"):
            market(ex)
        assert ex.order_state_uncertain
        assert ex.base_quantity == 0
        assert not store.list_trades()
        assert store.pending_live_order()
        monkeypatch.setattr(exchange, "order_trades", good_fills)
        assert ex.reconcile_uncertain_order()
    assert exchange.posts == 1


def test_writing_intent_failure_prevents_post(tmp_path, monkeypatch):
    path = tmp_path / "live.sqlite3"
    exchange = Exchange(path)
    with PaperStore(path, async_writes=False) as store:
        ex = executor(exchange, store)
        monkeypatch.setattr(store, "begin_live_order", lambda *a: (_ for _ in ()).throw(OSError()))
        with pytest.raises(OSError):
            market(ex)
        assert ex.order_state_uncertain
    assert exchange.posts == 0


def test_ledger_failure_rolls_back_snapshot_intent_and_in_memory_account(tmp_path):
    path = tmp_path / "live.sqlite3"
    exchange = Exchange(path)
    with PaperStore(path, async_writes=False) as store:
        ex = executor(exchange, store)
        # Force the ledger row to fail after the SQLite transaction has deleted the
        # intent and updated the account record, not before the transaction starts.
        store._db.execute(
            "CREATE TRIGGER fail_ledger BEFORE INSERT ON paper_trades "
            "BEGIN SELECT RAISE(ABORT, 'commit fault'); END"
        )
        with pytest.raises(Exception, match="commit fault"):
            market(ex)
        assert store.load_state(KEY)["account"]["base_quantity"] == 0
        assert store.pending_live_order()
        assert ex.order_state_uncertain
        assert ex.base_quantity == 0
        assert not ex.trades
        store._db.execute("DROP TRIGGER fail_ledger")
    with PaperStore(path, async_writes=False) as store:
        ex = executor(exchange, store)
        assert ex.reconcile_uncertain_order()
        assert store.load_state(KEY)["account"]["base_quantity"] == pytest.approx(0.1)
        assert store.pending_live_order() is None
        assert len(store.list_trades()) == 1
    assert exchange.posts == 1


def test_mismatched_order_identity_does_not_release_intent(tmp_path, monkeypatch):
    path = tmp_path / "live.sqlite3"
    exchange = Exchange(path)
    exchange.place_mode = "after"
    monkeypatch.setattr(
        exchange, "get_order_by_client_id",
        lambda *args: replace(exchange.order, client_order_id="not-the-same"),
    )
    with PaperStore(path, async_writes=False) as store:
        with pytest.raises(RuntimeError, match="identity"):
            market(executor(exchange, store))
        assert store.pending_live_order()
        assert not store.list_trades()


def test_database_account_network_and_writer_are_isolated(tmp_path):
    path = tmp_path / "live.sqlite3"
    exchange = Exchange(path)
    with exclusive_live_worker(str(path)), PaperStore(path, async_writes=False) as store:
        executor(exchange, store)
        with pytest.raises(RuntimeError, match="already owns"), exclusive_live_worker(str(path)):
            pytest.fail("second live worker acquired execution lock")
        exchange.uid = 43
        with pytest.raises(RuntimeError, match="different exchange account"):
            executor(exchange, store)
        exchange.uid = 42
        exchange.testnet = False
        with pytest.raises(RuntimeError, match="different exchange account"):
            executor(exchange, store)
    with exclusive_live_worker(str(path)):
        pass


def test_live_factory_constructs_executor_without_making_network_calls(monkeypatch):
    import app.engine_setup as es

    monkeypatch.setattr(es, "settings", SimpleNamespace(
        trading_mode="live", binance_testnet=True, binance_api_key="fake",
        binance_api_secret="fake", symbol="btcusdt", prefer_maker=True,
        effective_fee_rate=lambda: 0.001,
    ))
    ex = es._build_executor()
    assert ex.symbol == "BTCUSDT"
    assert callable(ex.buy_limit)
    assert isinstance(ex.client, BinanceRestClient)
    with pytest.raises(RuntimeError, match="durable journal"):
        ex._place_market_order_once(side="BUY", reason="mock", quote_order_qty=10)


def test_live_engine_startup_stops_before_balance_sync_when_order_unknown(tmp_path, monkeypatch):
    import app.engine_loop as engine

    path = tmp_path / "live.sqlite3"
    exchange = Exchange(path)
    exchange.place_mode = "before"
    with PaperStore(path, async_writes=False) as store:
        with pytest.raises(LookupError):
            market(executor(exchange, store))

    ex = LiveExecutor(exchange, symbol="BTCUSDT", fee_rate=0.001)
    monkeypatch.setattr(ex, "sync_balances", lambda: pytest.fail("balance sync must not run"))
    monkeypatch.setattr(engine.es, "_build_executor", lambda: ex)
    monkeypatch.setattr(engine.es, "executor", None)
    monkeypatch.setattr(engine, "state", SimpleNamespace())
    monkeypatch.setattr(engine, "settings", SimpleNamespace(
        symbol="btcusdt", trading_mode="live", store_path=str(path), binance_testnet=True,
    ))
    killed = []
    monkeypatch.setattr(engine, "risk", SimpleNamespace(activate_kill_switch=killed.append))
    with pytest.raises(RuntimeError, match="refusing to start") as blocked:
        asyncio.run(engine.run())
    assert "Unresolved live order intent" in str(blocked.value.__cause__)
    assert killed
    with exclusive_live_worker(str(path)), PaperStore(path, async_writes=False) as store:
        assert store.pending_live_order()
    assert exchange.posts == 1


def test_live_restart_with_invisible_protection_keeps_readiness_closed(tmp_path, monkeypatch):
    from time import monotonic

    from fastapi.testclient import TestClient

    import app.api as api
    import app.config as config
    import app.engine_loop as engine

    path = tmp_path / "live.sqlite3"

    class ProtectionExchange(Exchange):
        oco_posts = 0

        def free_balance(self, asset):
            return 0.1

        def place_oco_order(self, **params):
            self.oco_posts += 1
            with PaperStore(path, async_writes=False) as observer:
                assert observer.pending_live_order()["client_id"] == params["client_order_id"]
            raise ProcessExit()

        def get_order_list_by_client_id(self, symbol, client_order_id):
            raise LookupError("accepted order list is not visible yet")

    exchange = ProtectionExchange(path)
    with PaperStore(path, async_writes=False) as store:
        ex = executor(exchange, store)
        market(ex)
        with pytest.raises(ProcessExit):
            ex.ensure_protective_oco(
                current_price=100, take_profit_pct=2, stop_loss_pct=2,
            )
        assert exchange.posts == exchange.oco_posts == 1

    ex = LiveExecutor(exchange, symbol="BTCUSDT", fee_rate=0.001)
    state = SimpleNamespace(paused=False, exchange_reconciliation_max_age_seconds=30)
    killed = []
    settings = SimpleNamespace(symbol="btcusdt", trading_mode="live", store_path=str(path), binance_testnet=True)
    monkeypatch.setattr(ex, "sync_balances", lambda: pytest.fail("balance sync must not run"))
    monkeypatch.setattr(engine.es, "_build_executor", lambda: ex)
    monkeypatch.setattr(engine.es, "executor", None)
    monkeypatch.setattr(engine, "state", state)
    monkeypatch.setattr(engine, "settings", settings)
    monkeypatch.setattr(engine, "risk", SimpleNamespace(activate_kill_switch=killed.append))
    with pytest.raises(RuntimeError, match="refusing to start"):
        asyncio.run(engine.run())
    assert killed
    # Even with otherwise fresh market/audit evidence, the API must not claim readiness.
    state.exchange_reconciliation = {"status": "pass"}
    state.exchange_reconciled_at_monotonic = monotonic()
    state.live_entry_cost_calibrated = True
    monkeypatch.setattr(api, "state", state)
    monkeypatch.setattr(config, "settings", settings)
    monkeypatch.setattr(api, "health", lambda: {
        "engine": "running", "market_data_connected": True, "kill_switch": False, "emergency": False,
    })
    result = TestClient(api.app).get("/ready")
    assert result.status_code == 503
    assert set(result.json()["blockers"]) >= {"order_state_uncertain", "position_unprotected"}
    assert exchange.posts == exchange.oco_posts == 1
