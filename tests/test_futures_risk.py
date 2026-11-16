from __future__ import annotations

import pytest

from app.futures_risk import (
    check_liquidation_buffer,
    estimate_usdm_round_trip_cost,
    size_usdm_position,
)


def test_futures_cost_includes_both_fees_spread_slippage_and_funding():
    costs = estimate_usdm_round_trip_cost(
        entry_fee_rate=0.0005,
        exit_fee_rate=0.0005,
        spread_bps=2,
        entry_slippage_bps=1,
        exit_slippage_bps=2,
        funding_rate_per_event=0.0001,
        expected_funding_events=2,
    )
    assert costs.entry_fee_bps == 5
    assert costs.exit_fee_bps == 5
    assert costs.spread_bps == 2
    assert costs.slippage_bps == 3
    assert costs.funding_bps == 2
    assert costs.total_bps == 17


def test_futures_funding_is_charged_conservatively_even_if_rate_is_negative():
    costs = estimate_usdm_round_trip_cost(
        entry_fee_rate=0.0004,
        exit_fee_rate=0.0004,
        spread_bps=1,
        entry_slippage_bps=0,
        exit_slippage_bps=0,
        funding_rate_per_event=-0.0002,
        expected_funding_events=1,
    )
    assert costs.funding_bps == 2


def test_futures_size_is_stop_risk_and_margin_capped_at_one_x():
    size = size_usdm_position(
        equity_usdt=100,
        risk_per_trade_pct=0.35,
        stop_distance_pct=0.5,
        leverage=1,
        max_leverage=1,
        max_margin_fraction=0.25,
    )
    assert size.notional_usdt == pytest.approx(25)
    assert size.initial_margin_usdt == pytest.approx(25)
    assert size.stop_risk_usdt == pytest.approx(0.125)
    assert size.leverage == 1


def test_futures_rejects_leverage_above_cap():
    with pytest.raises(ValueError, match="leverage"):
        size_usdm_position(
            equity_usdt=100, risk_per_trade_pct=0.35, stop_distance_pct=0.5,
            leverage=2, max_leverage=1,
        )


def test_liquidation_buffer_requires_stop_between_mark_and_liquidation():
    safe = check_liquidation_buffer(
        side="long", mark_price=100, liquidation_price=90, stop_price=96,
        min_buffer_bps=500,
    )
    unsafe = check_liquidation_buffer(
        side="long", mark_price=100, liquidation_price=95, stop_price=96,
        min_buffer_bps=200,
    )
    assert safe.safe
    assert safe.distance_bps == pytest.approx(600)
    assert not unsafe.safe
    assert unsafe.reason == "liquidation_buffer_too_small"


def test_missing_or_wrong_side_liquidation_price_fails_closed():
    missing = check_liquidation_buffer(
        side="short", mark_price=100, liquidation_price=None, stop_price=102,
    )
    wrong = check_liquidation_buffer(
        side="short", mark_price=100, liquidation_price=99, stop_price=102,
    )
    assert not missing.safe and missing.reason == "liquidation_price_missing"
    assert not wrong.safe and wrong.reason == "invalid_short_liquidation_geometry"



def test_futures_cost_gate_uses_same_two_times_friction_rule():
    from app.futures_risk import passes_futures_cost_gate

    costs = estimate_usdm_round_trip_cost(
        entry_fee_rate=0.0005,
        exit_fee_rate=0.0005,
        spread_bps=2,
        entry_slippage_bps=1,
        exit_slippage_bps=1,
        funding_rate_per_event=0.0001,
        expected_funding_events=1,
    )
    assert costs.total_bps == 15
    assert not passes_futures_cost_gate(gross_expected_move_bps=29, costs=costs)
    assert passes_futures_cost_gate(gross_expected_move_bps=30, costs=costs)
    with pytest.raises(ValueError, match=">= 2.0"):
        passes_futures_cost_gate(
            gross_expected_move_bps=100, costs=costs, min_cost_multiple=1.5,
        )
