from app.paper import PaperExecutor


def test_paper_account_snapshot_restores_position_and_trade_history():
    first = PaperExecutor(1000, 0.001)
    first.buy(notional_usdt=25, price=100, reason="test")
    saved = first.snapshot()
    restored = PaperExecutor(1000, 0.001)
    restored.restore(saved)
    assert restored.cash_usdt == first.cash_usdt
    assert restored.base_quantity == first.base_quantity
    assert restored.average_entry_price == first.average_entry_price
    assert restored.trades == first.trades


def test_restore_rejects_invalid_negative_position():
    executor = PaperExecutor(1000, 0.001)
    snapshot = executor.snapshot()
    snapshot["base_quantity"] = -1
    try:
        executor.restore(snapshot)
    except ValueError as exc:
        assert "position" in str(exc)
    else:
        raise AssertionError("negative position must be rejected")
