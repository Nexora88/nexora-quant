"""Retail structural constraints — honest math, not marketing.

Binance Spot + individual fee tiers + L2 scalping is a hostile combination:
round-trip fees often exceed the size of microstructure signals. This module
does not invent alpha; it quantifies the fee wall and recommends posture.

Use for:
- dashboard / status honesty
- gating unrealistic expected_alpha vs fee
- paper vs live posture notes
"""
from __future__ import annotations

from dataclasses import dataclass

from app.fees import FeeSchedule, schedule_from_settings


@dataclass(frozen=True, slots=True)
class FeeWall:
    """What the exchange extracts before any edge can exist."""

    taker_bps: float
    maker_bps: float
    round_trip_taker_bps: float
    round_trip_maker_entry_taker_exit_bps: float
    vip_level: int
    use_bnb: bool
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RealityReport:
    """Structural verdict for this desk configuration."""

    fee_wall: FeeWall
    min_gross_alpha_bps_to_clear_fees: float
    posture: str  # "defensive" | "selective" | "aggressive_not_recommended"
    can_scalp_sub_10bps: bool
    summary: str
    recommendations: tuple[str, ...]


def build_fee_wall(
    *,
    fee_rate: float = 0.001,
    vip_level: int = 0,
    use_bnb_discount: bool = False,
) -> FeeWall:
    sched = schedule_from_settings(
        fee_rate=fee_rate,
        vip_level=vip_level,
        use_bnb_discount=use_bnb_discount,
    )
    taker = sched.taker_rate() * 10_000.0
    maker = sched.maker_rate() * 10_000.0
    notes: list[str] = []
    if vip_level == 0 and not use_bnb_discount and abs(fee_rate - 0.001) < 1e-12:
        notes.append("vip0_taker_10bps_each_side")
    if use_bnb_discount:
        notes.append("bnb_discount_applied")
    if vip_level >= 3:
        notes.append("vip_tier_helps_but_does_not_create_alpha")
    return FeeWall(
        taker_bps=taker,
        maker_bps=maker,
        round_trip_taker_bps=taker * 2.0,
        round_trip_maker_entry_taker_exit_bps=maker + taker,
        vip_level=vip_level,
        use_bnb=use_bnb_discount,
        notes=tuple(notes),
    )


def assess_retail_desk(
    *,
    fee_rate: float = 0.001,
    vip_level: int = 0,
    use_bnb_discount: bool = False,
    prefer_maker: bool = False,
    expected_alpha_bps: float = 15.0,
    starting_cash_usdt: float = 100.0,
) -> RealityReport:
    """Verdict: can this fee + alpha configuration clear the wall?"""
    wall = build_fee_wall(
        fee_rate=fee_rate,
        vip_level=vip_level,
        use_bnb_discount=use_bnb_discount,
    )
    rt = (
        wall.round_trip_maker_entry_taker_exit_bps
        if prefer_maker
        else wall.round_trip_taker_bps
    )
    min_gross = rt + 2.0  # small buffer for spread/impact
    can_sub10 = rt < 10.0  # only VIP/BNB maker paths approach this
    recs: list[str] = []

    if expected_alpha_bps < rt:
        posture = "defensive"
        summary = (
            f"expected_alpha {expected_alpha_bps:.1f}bps < round-trip fee {rt:.1f}bps — "
            "edge gate should block most entries (correct behavior, not a bug)."
        )
        recs.append("do_not_force_trades_to_satisfy_boredom")
        recs.append("raise_tp_or_lower_fees_via_bnb_vip_maker_before_expecting_pnl")
    elif expected_alpha_bps < min_gross + 5.0:
        posture = "selective"
        summary = (
            f"thin edge after fees (~{expected_alpha_bps - rt:.1f}bps). "
            "Few high-quality trades only; churn will erase expectancy."
        )
        recs.append("keep_max_trades_per_hour_low")
        recs.append("prefer_maker_entry_when_possible")
    else:
        posture = "selective"
        summary = (
            f"configured alpha {expected_alpha_bps:.1f}bps clears ~{rt:.1f}bps fees on paper. "
            "Live adverse selection still applies; paper ≠ live."
        )
        recs.append("validate_48h_paper_fee_net_before_live")

    if starting_cash_usdt < 500:
        recs.append("sub_500_usdt_accounts_pay_full_retail_fee_wall_with_tiny_size")
    if not use_bnb_discount:
        recs.append("enable_bnb_fee_discount_if_available_on_account")
    if not prefer_maker:
        recs.append("taker_taker_round_trip_is_the_hardest_path")
    if vip_level == 0:
        recs.append("vip0_spot_l2_scalp_is_structurally_hostile")

    recs.append("python_vps_is_not_colocated_hft_do_not_compete_on_latency")
    recs.append("learner_needs_dozens_of_closed_trades_noise_before_that")

    return RealityReport(
        fee_wall=wall,
        min_gross_alpha_bps_to_clear_fees=min_gross,
        posture=posture,
        can_scalp_sub_10bps=can_sub10,
        summary=summary,
        recommendations=tuple(recs),
    )


def to_status_dict(report: RealityReport) -> dict:
    w = report.fee_wall
    return {
        "posture": report.posture,
        "summary": report.summary,
        "min_gross_alpha_bps": round(report.min_gross_alpha_bps_to_clear_fees, 2),
        "can_scalp_sub_10bps": report.can_scalp_sub_10bps,
        "fee_wall": {
            "taker_bps": round(w.taker_bps, 2),
            "maker_bps": round(w.maker_bps, 2),
            "rt_taker_bps": round(w.round_trip_taker_bps, 2),
            "rt_maker_taker_bps": round(w.round_trip_maker_entry_taker_exit_bps, 2),
            "vip": w.vip_level,
            "bnb": w.use_bnb,
        },
        "recommendations": list(report.recommendations)[:8],
    }
