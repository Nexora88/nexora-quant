"""BTC macro filter: block altcoin entries during BTC liquidation-style wicks.

When trading SOL/ETH/BNB, a sharp BTC drop often cascades regardless of local OBI.
This module tracks BTC mid returns and raises ``block_long`` for a short cooldown.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(slots=True)
class BtcFilterSnapshot:
    block_long: bool
    last_ret_bps: float
    wick_bps: float
    cooldown_left: int
    detail: str


class BtcTrendFilter:
    def __init__(
        self,
        *,
        wick_jump_bps: float = 40.0,
        cooldown_ticks: int = 12,
        window: int = 60,
    ) -> None:
        self.wick_jump_bps = wick_jump_bps
        self.cooldown_ticks = max(1, cooldown_ticks)
        self._mids: deque[float] = deque(maxlen=window)
        self._cooldown = 0
        self._last_wick = 0.0
        self._last_ret = 0.0

    def snapshot(self) -> BtcFilterSnapshot:
        if self._cooldown > 0:
            return BtcFilterSnapshot(
                True,
                self._last_ret,
                self._last_wick,
                self._cooldown,
                f"btc_wick_{self._last_wick:.0f}bps_cd={self._cooldown}",
            )
        return BtcFilterSnapshot(False, self._last_ret, 0.0, 0, "btc_ok")

    def tick_cooldown(self) -> BtcFilterSnapshot:
        """Advance cooldown without a new mid (use when BTC feed is separate)."""
        if self._cooldown > 0:
            self._cooldown -= 1
        return self.snapshot()

    def update(self, mid: float) -> BtcFilterSnapshot:
        if mid <= 0:
            return self.tick_cooldown()
        if self._mids:
            prev = self._mids[-1]
            if prev > 0:
                ret = (mid / prev - 1.0) * 10_000.0
                self._last_ret = ret
                if ret <= -self.wick_jump_bps:
                    self._cooldown = self.cooldown_ticks
                    self._last_wick = abs(ret)
        self._mids.append(mid)
        if self._cooldown > 0:
            self._cooldown -= 1
        return self.snapshot()
