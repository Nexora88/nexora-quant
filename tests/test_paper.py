import pytest

from app.paper import PaperExecutor


def test_buy_and_sell_accounts_for_entry_and_exit_fees():
    paper = PaperExecutor(1000, 0.001)
    bought = paper.buy(notional_usdt=100, price=10, reason="test")
    assert bought["quantity"] == 10
    assert paper.cash_usdt == pytest.approx(899.9)
    sold = paper.sell_all(price=11)
    assert sold is not None
    assert sold["entry_fee_allocated_usdt"] == pytest.approx(0.1)
    assert sold["pnl_usdt"] == pytest.approx(9.79)
    assert paper.realized_pnl_usdt == pytest.approx(9.79)
    assert paper.fees_paid_usdt == pytest.approx(0.21)
    assert paper.base_quantity == 0


def test_partial_sell_allocates_entry_fee_proportionally():
    paper = PaperExecutor(1000, 0.001)
    paper.buy(notional_usdt=100, price=10, reason="test")
    first = paper.sell_quantity(quantity=4, price=11, reason="partial")
    assert first is not None
    assert first["entry_fee_allocated_usdt"] == pytest.approx(0.04)
    assert first["pnl_usdt"] == pytest.approx(3.916)
    assert paper.entry_fee_remaining_usdt == pytest.approx(0.06)

    second = paper.sell_all(price=12)
    assert second is not None
    assert second["entry_fee_allocated_usdt"] == pytest.approx(0.06)
    assert second["pnl_usdt"] == pytest.approx(11.868)
    assert paper.realized_pnl_usdt == pytest.approx(15.784)
    assert paper.entry_fee_remaining_usdt == pytest.approx(0.0)


def test_buy_rejects_insufficient_cash_including_fee():
    paper = PaperExecutor(10, 0.001)
    with pytest.raises(ValueError):
        paper.buy(notional_usdt=10, price=1, reason="test")
