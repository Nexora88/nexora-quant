import pytest

from app.research_validation import (
    PortfolioLedger, portfolio_metrics, simulate_queue_fill, walk_forward_splits,
)


def test_portfolio_uses_one_shared_cash_pool_and_position_cap():
    book = PortfolioLedger(100.0, fee_rate=0.001, max_positions=2)
    assert book.buy("btcusdt", 0.4, 100.0)
    assert book.buy("ethusdt", 0.01, 2000.0)
    assert not book.buy("solusdt", 0.1, 100.0)
    assert book.cash == pytest.approx(39.94)
    assert book.sell("btcusdt", 0.4, 101.0) > 0
    assert "btcusdt" not in book.positions


def test_portfolio_rejects_missing_marks_and_oversells():
    book = PortfolioLedger(100.0)
    book.buy("btcusdt", 0.1, 100.0)
    with pytest.raises(ValueError):
        book.sell("btcusdt", 0.2, 100.0)
    with pytest.raises(ValueError):
        book.mark(1, {})


def test_metrics_report_net_return_drawdown_and_expectancy():
    result = portfolio_metrics(
        [{"equity": 100.0}, {"equity": 110.0}, {"equity": 99.0}],
        realized_pnl=-1.0, trade_pnls=[2.0, -3.0],
    )
    assert result["net_return_pct"] == pytest.approx(-1.0)
    assert result["max_drawdown_pct"] == pytest.approx(10.0)
    assert result["expectancy_per_trade"] == pytest.approx(-0.5)


def test_walk_forward_windows_are_chronological_and_disjoint():
    splits = walk_forward_splits(range(200), step_fraction=0.2)
    assert splits
    first = splits[0]
    assert first["train_end"] == first["validation_start"]
    assert first["validation_end"] == first["test_start"]
    assert first["test_end"] == 140
    assert len(splits) == 4
    assert splits[1]["train_start"] == 0
    assert splits[1]["train_end"] > first["train_end"]
    assert all(a["test_end"] <= b["train_start"] + 100 for a, b in zip(splits, splits[1:]))


def test_walk_forward_rejects_too_little_data():
    with pytest.raises(ValueError):
        walk_forward_splits(range(2))


def test_queue_fill_only_credits_volume_after_queue_is_cleared():
    no_fill = simulate_queue_fill(
        requested_quantity=10, displayed_ahead_quantity=100,
        traded_through_quantity=50,
    )
    assert no_fill["estimated_fill_quantity"] == 0
    partial = simulate_queue_fill(
        requested_quantity=10, displayed_ahead_quantity=100,
        traded_through_quantity=120, participation_cap=0.1,
    )
    assert partial["estimated_fill_quantity"] == pytest.approx(2.0)
