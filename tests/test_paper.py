import pytest
from app.paper import PaperExecutor

def test_buy_and_sell_accounts_for_fees():
    paper = PaperExecutor(1000, 0.001)
    bought = paper.buy(notional_usdt=100, price=10, reason="test")
    assert bought["quantity"] == 10
    assert paper.cash_usdt == pytest.approx(899.9)
    sold = paper.sell_all(price=11)
    assert sold is not None
    assert sold["pnl_usdt"] == pytest.approx(9.79)
    assert sold["entry_fee_allocated_usdt"] == pytest.approx(0.10)
    assert paper.base_quantity == 0
    assert paper.realized_pnl_usdt == pytest.approx(9.79)
    assert paper.snapshot()["equity_usdt"] == pytest.approx(1009.79)

def test_buy_rejects_insufficient_cash():
    paper = PaperExecutor(10, 0.001)
    with pytest.raises(ValueError):
        paper.buy(notional_usdt=10, price=1, reason="test")

def test_partial_sell_allocates_entry_fee_and_preserves_remaining_cost():
    paper = PaperExecutor(1000, 0.001)
    paper.buy(notional_usdt=100, price=10, reason="entry")
    partial = paper.sell_quantity(quantity=4, price=11, reason="partial")
    assert partial is not None
    assert partial["entry_fee_allocated_usdt"] == pytest.approx(0.04)
    assert partial["pnl_usdt"] == pytest.approx(3.916)
    assert paper.base_quantity == pytest.approx(6)
    assert paper.entry_fees_remaining_usdt == pytest.approx(0.06)

    restored = PaperExecutor(1000, 0.001)
    restored.restore(paper.snapshot())
    final = restored.sell_all(price=11)
    assert final is not None
    assert final["entry_fee_allocated_usdt"] == pytest.approx(0.06)
    assert restored.realized_pnl_usdt == pytest.approx(9.79)
