import pytest
from app.paper import PaperExecutor

def test_buy_and_sell_accounts_for_fees():
    paper = PaperExecutor(1000, 0.001)
    bought = paper.buy(notional_usdt=100, price=10, reason="test")
    assert bought["quantity"] == 10
    assert paper.cash_usdt == pytest.approx(899.9)
    sold = paper.sell_all(price=11)
    assert sold is not None
    assert sold["pnl_usdt"] == pytest.approx(8.9)
    assert paper.base_quantity == 0

def test_buy_rejects_insufficient_cash():
    paper = PaperExecutor(10, 0.001)
    with pytest.raises(ValueError):
        paper.buy(notional_usdt=10, price=1, reason="test")
