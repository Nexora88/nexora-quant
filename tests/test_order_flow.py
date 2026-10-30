from __future__ import annotations

import time

from app.order_flow import OrderFlowAccumulator


def test_flow_warms_then_ready():
    of = OrderFlowAccumulator(hold_seconds=1.0, min_samples=5, min_abs_pressure=0.15)
    first = of.update(imbalance=0.8, micro_premium_bps=2.0)
    assert first.ready is False
    for _ in range(12):
        time.sleep(0.05)
        fp = of.update(imbalance=0.82, micro_premium_bps=2.5)
    assert fp.samples >= 5
    assert fp.pressure > 0
    assert fp.bullish or fp.note.startswith("flow=")


def test_weak_flow_not_ready():
    of = OrderFlowAccumulator(hold_seconds=1.0, min_samples=4, min_abs_pressure=0.25)
    for _ in range(8):
        time.sleep(0.03)
        fp = of.update(imbalance=0.52, micro_premium_bps=0.0)
    assert fp.ready is False
