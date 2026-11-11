"""Exit rules: peak trail, SL, TP — critical for non-zombie positions."""
from app.strategy import exit_reason


def test_stop_loss():
    assert (
        exit_reason(
            bid=99.0,
            average_entry=100.0,
            take_profit_pct=0.55,
            stop_loss_pct=0.18,
            trailing_stop_pct=0.12,
            peak_price=100.0,
            target_price=None,
        )
        == "stop_loss"
    )


def test_take_profit():
    assert (
        exit_reason(
            bid=100.6,
            average_entry=100.0,
            take_profit_pct=0.55,
            stop_loss_pct=0.18,
            trailing_stop_pct=0.12,
            peak_price=100.6,
            target_price=None,
        )
        == "take_profit"
    )


def test_trailing_uses_peak_not_entry():
    # Peak must ratchet higher in engine; here peak=101 implies trail floor ~100.878
    assert (
        exit_reason(
            bid=100.85,
            average_entry=100.0,
            take_profit_pct=0.55,
            stop_loss_pct=0.18,
            trailing_stop_pct=0.12,
            peak_price=101.0,
            target_price=None,
        )
        == "trailing_stop"
    )


def test_no_exit_in_band():
    assert (
        exit_reason(
            bid=100.2,
            average_entry=100.0,
            take_profit_pct=0.55,
            stop_loss_pct=0.18,
            trailing_stop_pct=0.12,
            peak_price=100.2,
            target_price=None,
        )
        is None
    )
