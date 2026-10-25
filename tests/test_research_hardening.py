import pytest

from app.depth_book import DepthBook
from app.portfolio import size_from_free_cash
from app.simulation import ExecutionSimulator
from app.storage import PaperStore


def test_dynamic_sizing_uses_fraction_but_respects_caps_and_fees():
    decision = size_from_free_cash(free_usdt=1000, allocation_fraction=0.8,
                                   fee_rate=0.001, max_order_usdt=500)
    assert decision.notional_usdt == pytest.approx(500)
    small = size_from_free_cash(free_usdt=10, allocation_fraction=0.8,
                                fee_rate=0.001, max_order_usdt=500)
    assert small.notional_usdt == pytest.approx(7.992008)


def test_dynamic_sizing_returns_zero_below_minimum():
    assert size_from_free_cash(free_usdt=2).notional_usdt == 0


def test_sqlite_state_and_trade_idempotency_survive_reopen(tmp_path):
    path = tmp_path / "paper.sqlite3"
    with PaperStore(path) as store:
        store.save_state("account", {"cash": 120.5, "position": 0.2})
        assert store.append_trade({"side": "buy", "qty": 0.2}, event_key="evt-1")
        assert not store.append_trade({"side": "buy", "qty": 0.2}, event_key="evt-1")
    with PaperStore(path) as store:
        assert store.load_state("account") == {"cash": 120.5, "position": 0.2}
        assert len(store.list_trades()) == 1


def test_simulator_applies_adverse_slippage_and_is_reproducible():
    sim1 = ExecutionSimulator(slippage_bps=5, latency_ms=100, seed=7)
    sim2 = ExecutionSimulator(slippage_bps=5, latency_ms=100, seed=7)
    buy1 = sim1.fill(side="buy", reference_price=100, quantity=2)
    buy2 = sim2.fill(side="buy", reference_price=100, quantity=2)
    assert buy1 == buy2
    assert buy1.fill_price >= 100
    assert buy1.latency_ms >= 0


def test_simulator_can_model_partial_fills():
    result = ExecutionSimulator(partial_fill_probability=1, seed=1).fill(
        side="sell", reference_price=100, quantity=10
    )
    assert 0 < result.filled_quantity < 10
    assert not result.complete


def test_depth_book_applies_contiguous_updates_and_deletes_zero_levels():
    book = DepthBook()
    book.load_snapshot(last_update_id=100, bids=[(99, 2), (98, 3)], asks=[(101, 1)])
    assert book.apply_diff(first_update_id=101, final_update_id=102,
                           bids=[(99, 0), (100, 1)], asks=[(101, 2)])
    assert book.best_bid == (100.0, 1.0)
    assert book.best_ask == (101.0, 2.0)
    assert not book.apply_diff(first_update_id=101, final_update_id=102,
                               bids=[], asks=[])


def test_depth_book_invalidates_on_sequence_gap():
    book = DepthBook()
    book.load_snapshot(last_update_id=100, bids=[(99, 2)], asks=[(101, 1)])
    assert not book.apply_diff(first_update_id=103, final_update_id=104,
                               bids=[(100, 1)], asks=[])
    assert not book.synchronized
    assert not book.apply_diff(first_update_id=105, final_update_id=106,
                               bids=[], asks=[])
