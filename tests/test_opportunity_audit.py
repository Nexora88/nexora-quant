import pytest

from app.opportunity_audit import audit_blocked_candidates


def test_blocked_candidate_uses_future_executable_bid_and_round_trip_costs():
    result = audit_blocked_candidates(
        [{"timestamp_ns": 1_000_000_000, "entry_ask": 100.0,
          "blockers": ["macro_not_ready", "trade_flow_not_ready"]}],
        [
            {"timestamp_ns": 31_000_000_000, "bid": 101.0, "ask": 101.1},
            {"timestamp_ns": 61_000_000_000, "bid": 99.0, "ask": 99.1},
        ],
        horizons_seconds=(30, 60),
        fee_rate=0.001,
        slippage_bps_per_side=0,
    )
    first = result["by_horizon"]["30"]
    second = result["by_horizon"]["60"]
    assert first["evaluated"] == 1
    assert first["mean_net_bps"] == pytest.approx(
        ((101.0 * 0.999) / (100.0 * 1.001) - 1) * 10_000
    )
    assert second["mean_net_bps"] < 0
    assert set(result["by_blocker"]) == {"macro_not_ready", "trade_flow_not_ready"}


def test_audit_never_uses_quote_before_horizon_or_stale_quote():
    result = audit_blocked_candidates(
        [{"timestamp_ns": 10_000_000_000, "entry_ask": 100,
          "blockers": ["book_not_ready"]}],
        [
            {"timestamp_ns": 39_000_000_000, "bid": 110, "ask": 111},
            {"timestamp_ns": 50_000_000_000, "bid": 90, "ask": 91},
        ],
        horizons_seconds=(30,),
        max_quote_delay_seconds=2,
    )
    assert result["by_horizon"]["30"]["evaluated"] == 0
    assert result["outcomes"][0]["net_return_bps"]["30"] is None


def test_audit_leaves_unobserved_future_horizons_unscored():
    result = audit_blocked_candidates(
        [{"timestamp_ns": 10_000_000_000, "entry_ask": 100,
          "blockers": ["spread_too_wide"]}],
        [{"timestamp_ns": 11_000_000_000, "bid": 105, "ask": 106}],
        horizons_seconds=(30, 60),
    )
    assert result["by_horizon"]["30"]["evaluated"] == 0
    assert result["by_horizon"]["60"]["evaluated"] == 0


def test_audit_rejects_invalid_cost_assumptions():
    with pytest.raises(ValueError):
        audit_blocked_candidates([], [], fee_rate=-0.1)
