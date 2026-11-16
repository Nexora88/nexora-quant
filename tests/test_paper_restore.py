import pytest

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

def test_restore_policy_preserves_cash_and_open_position_without_rebasing():
    from app.paper import restore_paper_account

    first = PaperExecutor(1000, 0.001)
    first.buy(notional_usdt=100, price=10, reason="entry")
    first.sell_all(price=9, reason="loss")
    first.buy(notional_usdt=50, price=8, reason="new_entry")
    saved = first.snapshot()

    restored = PaperExecutor(1000, 0.001)
    has_position = restore_paper_account(restored, saved, resume_position=True)
    assert has_position is True
    assert restored.cash_usdt == first.cash_usdt
    assert restored.starting_cash_usdt == first.starting_cash_usdt
    assert restored.base_quantity == first.base_quantity
    assert restored.entry_fees_remaining_usdt == first.entry_fees_remaining_usdt


def test_restore_policy_refuses_to_discard_open_position():
    from app.paper import restore_paper_account

    source = PaperExecutor(1000, 0.001)
    source.buy(notional_usdt=50, price=10, reason="entry")
    restored = PaperExecutor(1000, 0.001)
    try:
        restore_paper_account(restored, source.snapshot(), resume_position=False)
    except RuntimeError as exc:
        assert "refusing to discard" in str(exc)
    else:
        raise AssertionError("open paper position must not be silently discarded")

def test_legacy_open_position_reconstructs_remaining_entry_fees_from_trade_history():
    paper = PaperExecutor(1000, 0.001)
    paper.buy(notional_usdt=100, price=10, reason="entry")
    paper.sell_quantity(quantity=4, price=11, reason="partial")
    legacy = paper.snapshot()
    legacy.pop("entry_fees_remaining_usdt")

    restored = PaperExecutor(1000, 0.001)
    restored.restore(legacy)
    assert restored.entry_fees_remaining_usdt == pytest.approx(0.06)


def test_legacy_open_position_with_truncated_history_fails_closed():
    paper = PaperExecutor(1000, 0.001)
    paper.buy(notional_usdt=100, price=10, reason="entry")
    legacy = paper.snapshot()
    legacy.pop("entry_fees_remaining_usdt")
    legacy["trades"] = []

    restored = PaperExecutor(1000, 0.001)
    with pytest.raises(ValueError, match="history is incomplete"):
        restored.restore(legacy)
