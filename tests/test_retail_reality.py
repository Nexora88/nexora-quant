"""Retail fee-wall honesty."""
from __future__ import annotations

from app.retail_reality import assess_retail_desk, build_fee_wall


def test_vip0_taker_wall_blocks_tiny_alpha() -> None:
    wall = build_fee_wall(fee_rate=0.001, vip_level=0, use_bnb_discount=False)
    assert wall.round_trip_taker_bps >= 19.0  # ~20 bps
    report = assess_retail_desk(
        fee_rate=0.001,
        vip_level=0,
        use_bnb_discount=False,
        prefer_maker=False,
        expected_alpha_bps=5.0,
        starting_cash_usdt=100.0,
    )
    assert report.posture == "defensive"
    assert report.can_scalp_sub_10bps is False
    assert report.min_gross_alpha_bps_to_clear_fees > 15


def test_bnb_discount_lowers_wall() -> None:
    plain = build_fee_wall(fee_rate=0.001, vip_level=0, use_bnb_discount=False)
    disc = build_fee_wall(fee_rate=0.001, vip_level=0, use_bnb_discount=True)
    assert disc.round_trip_taker_bps < plain.round_trip_taker_bps


def test_maker_path_cheaper_than_taker_taker() -> None:
    report = assess_retail_desk(
        fee_rate=0.001,
        vip_level=1,
        use_bnb_discount=True,
        prefer_maker=True,
        expected_alpha_bps=25.0,
    )
    assert report.fee_wall.round_trip_maker_entry_taker_exit_bps <= report.fee_wall.round_trip_taker_bps
