from app.simulation import ExecutionSimulator


def test_buy_walks_ask_levels_and_uses_vwap() -> None:
    simulator = ExecutionSimulator(slippage_bps=0, latency_ms=0, seed=1, impact_coefficient=0)
    fill = simulator.fill(
        side="buy",
        reference_price=100,
        quantity=2,
        book_levels=[(100, 1), (102, 2)],
    )
    assert fill.filled_quantity == 2
    assert fill.complete
    assert fill.fill_price == 101


def test_sell_walks_bid_levels_and_uses_vwap() -> None:
    simulator = ExecutionSimulator(slippage_bps=0, latency_ms=0, seed=1, impact_coefficient=0)
    fill = simulator.fill(
        side="sell",
        reference_price=100,
        quantity=2,
        book_levels=[(101, 1), (99, 2)],
    )
    assert fill.filled_quantity == 2
    assert fill.complete
    assert fill.fill_price == 100


def test_visible_depth_caps_fill_when_book_is_too_thin() -> None:
    simulator = ExecutionSimulator(slippage_bps=0, latency_ms=0, seed=1, impact_coefficient=0)
    fill = simulator.fill(
        side="buy",
        reference_price=100,
        quantity=3,
        book_levels=[(100, 1.25)],
    )
    assert fill.filled_quantity == 1.25
    assert not fill.complete


def test_empty_visible_book_does_not_invent_a_fill() -> None:
    simulator = ExecutionSimulator(slippage_bps=0, latency_ms=0, seed=1, impact_coefficient=0)
    fill = simulator.fill(
        side="buy",
        reference_price=100,
        quantity=1,
        book_levels=[],
    )
    assert fill.filled_quantity == 0
    assert not fill.complete
