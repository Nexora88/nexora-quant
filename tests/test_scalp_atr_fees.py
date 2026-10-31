from __future__ import annotations

from app.atr_stops import WickStopState, compute_dynamic_targets, wick_aware_stop
from app.fees import FeeSchedule
from app.strategy import exit_reason


def test_scalp_tp_clears_fees():
    fee_rt = FeeSchedule(vip_level=0, use_bnb_discount=True).effective_round_trip() * 100
    t = compute_dynamic_targets(atr_pct=0.0015, regime="trend", fee_round_trip_pct=fee_rt)
    assert t.take_profit_pct >= fee_rt * 1.5
    assert 0.15 <= t.stop_loss_pct <= 0.35
    assert 0.40 <= t.take_profit_pct <= 1.0


def test_wick_stop_needs_confirmation():
    st = WickStopState()
    assert wick_aware_stop(move_pct=-0.20, stop_loss_pct=0.18, state=st, confirmations=2) is False
    assert wick_aware_stop(move_pct=-0.20, stop_loss_pct=0.18, state=st, confirmations=2) is True
    st2 = WickStopState()
    assert wick_aware_stop(move_pct=-0.20, stop_loss_pct=0.18, state=st2, confirmations=2) is False
    assert wick_aware_stop(move_pct=-0.05, stop_loss_pct=0.18, state=st2, confirmations=2) is False


def test_exit_reason_wick_soft():
    st = WickStopState()
    r1 = exit_reason(
        bid=99.8, average_entry=100.0, take_profit_pct=0.55, stop_loss_pct=0.18,
        trailing_stop_pct=0.12, peak_price=100.0, target_price=None,
        wick_confirmations=2, wick_state=st,
    )
    assert r1 is None
    r2 = exit_reason(
        bid=99.8, average_entry=100.0, take_profit_pct=0.55, stop_loss_pct=0.18,
        trailing_stop_pct=0.12, peak_price=100.0, target_price=None,
        wick_confirmations=2, wick_state=st,
    )
    assert r2 == "stop_loss"
