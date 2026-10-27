"""Dynamic Binance Spot fee schedule (BNB discount + VIP tiers).

Rates are approximate retail defaults and must be verified against current
Binance fee tables. This module does not call the exchange; it only prices
paper / expectancy math from configured VIP level and BNB-pay flag.
"""
from __future__ import annotations

from dataclasses import dataclass


# Spot taker / maker by VIP level (standard, no BNB). Source: typical Binance table.
_VIP_TAKER: dict[int, float] = {
    0: 0.0010,
    1: 0.0010,
    2: 0.0008,
    3: 0.0006,
    4: 0.0005,
    5: 0.0004,
    6: 0.0003,
    7: 0.0002,
    8: 0.0002,
    9: 0.0001,
}
_VIP_MAKER: dict[int, float] = {
    0: 0.0010,
    1: 0.0009,
    2: 0.0008,
    3: 0.0006,
    4: 0.0004,
    5: 0.0003,
    6: 0.0002,
    7: 0.0001,
    8: 0.0001,
    9: 0.0000,
}

# Paying fees in BNB historically ~25% off on many tiers (confirm live).
_BNB_DISCOUNT = 0.25


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    vip_level: int = 0
    use_bnb_discount: bool = False
    override_taker: float | None = None
    override_maker: float | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.vip_level <= 9:
            raise ValueError("vip_level must be in 0..9")
        for name, val in (("override_taker", self.override_taker), ("override_maker", self.override_maker)):
            if val is not None and not 0 <= val < 0.1:
                raise ValueError(f"{name} must be in [0, 0.1)")

    def taker_rate(self) -> float:
        if self.override_taker is not None:
            return self.override_taker
        base = _VIP_TAKER.get(self.vip_level, _VIP_TAKER[0])
        if self.use_bnb_discount:
            return base * (1.0 - _BNB_DISCOUNT)
        return base

    def maker_rate(self) -> float:
        if self.override_maker is not None:
            return self.override_maker
        base = _VIP_MAKER.get(self.vip_level, _VIP_MAKER[0])
        if self.use_bnb_discount:
            return base * (1.0 - _BNB_DISCOUNT)
        return base

    def effective_round_trip(self, *, assume_taker_exit: bool = True) -> float:
        """Entry+exit fee fraction of notional (taker in / taker or maker out)."""
        entry = self.taker_rate()
        exit_ = self.taker_rate() if assume_taker_exit else self.maker_rate()
        return entry + exit_

    def to_dict(self) -> dict:
        return {
            "vip_level": self.vip_level,
            "use_bnb_discount": self.use_bnb_discount,
            "taker_rate": self.taker_rate(),
            "maker_rate": self.maker_rate(),
            "round_trip_taker": self.effective_round_trip(assume_taker_exit=True),
        }


def schedule_from_settings(
    *,
    fee_rate: float,
    vip_level: int = 0,
    use_bnb_discount: bool = False,
    fee_rate_is_override: bool = True,
) -> FeeSchedule:
    """Build schedule. If fee_rate_is_override and fee_rate differs from VIP0, pin both sides."""
    if fee_rate_is_override and abs(fee_rate - 0.001) > 1e-12 and not use_bnb_discount and vip_level == 0:
        return FeeSchedule(vip_level=0, use_bnb_discount=False, override_taker=fee_rate, override_maker=fee_rate)
    return FeeSchedule(vip_level=vip_level, use_bnb_discount=use_bnb_discount)
