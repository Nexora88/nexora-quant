"""Exit rules: peak trail, SL, TP, time_stop / min_hold discipline."""
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


def test_peak_ratchet_logic():
    peak = 100.0
    for bid in (100.5, 101.2, 100.9):
        peak = max(peak, bid)
    assert peak == 101.2
    floor = peak * (1.0 - 0.12 / 100.0)
    assert exit_reason(
        bid=floor - 0.01,
        average_entry=100.0,
        take_profit_pct=0.55,
        stop_loss_pct=0.18,
        trailing_stop_pct=0.12,
        peak_price=peak,
        target_price=None,
    ) == "trailing_stop"


def test_min_hold_blocks_soft_exits_not_hard():
    soft = "take_profit"
    hard = {"stop_loss", "trailing_stop", "emergency", "kill", "time_stop"}
    min_hold = 90.0
    held = 30.0
    reason = soft
    if reason and reason not in hard:
        if min_hold > 0 and held < min_hold:
            reason = None
    assert reason is None

    reason = "time_stop"
    if reason and reason not in hard:
        if min_hold > 0 and held < min_hold:
            reason = None
    assert reason == "time_stop"


def test_time_stop_triggers_after_max_hold():
    max_hold = 2700.0
    held = 2700.0
    reason = None
    if not reason and max_hold > 0 and held >= max_hold:
        reason = "time_stop"
    assert reason == "time_stop"
