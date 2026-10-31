from __future__ import annotations

from app.paper import PaperExecutor


def test_restore_dust_clears():
    p = PaperExecutor(100.0, 0.001)
    p.restore({
        "starting_cash_usdt": 100.0,
        "cash_usdt": 99.5,
        "base_quantity": 1e-14,
        "average_entry_price": 50000.0,
        "realized_pnl_usdt": 0.0,
        "fees_paid_usdt": 0.0,
        "trade_count": 0,
        "trades": [],
    })
    assert p.base_quantity == 0.0
    assert p.average_entry_price == 0.0
