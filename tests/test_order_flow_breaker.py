"""Order-flow accumulation and drawdown circuit breaker."""
from __future__ import annotations

import time

from app.autonomous_policy import impact_capped_notional
from app.circuit_breaker import DrawdownCircuitBreaker
from app.order_flow import OrderFlowAccumulator


def test_flow_not_ready_on_flash():
    acc = OrderFlowAccumulator(hold_seconds=2.0, min_samples=5, min_abs_pressure=0.2)
    p = acc.update(imbalance=0.9, micro_premium_bps=3.0)
    assert p.ready is False


def test_flow_ready_after_sustained_pressure():
    acc = OrderFlowAccumulator(hold_seconds=1.0, min_samples=5, min_abs_pressure=0.15)
    for _ in range(12):
        p = acc.update(imbalance=0.72, micro_premium_bps=2.0)
        time.sleep(0.05)
    assert p.ready is True
    assert p.pressure > 0


def test_breaker_raises_score_and_sleeps():
    b = DrawdownCircuitBreaker(loss_streak=3, base_min_score=0.55, elevated_min_score=0.75, sleep_seconds=2.0)
    assert b.allow_entry() is True
    b.record_closed_pnl(-1.0)
    b.record_closed_pnl(-1.0)
    b.record_closed_pnl(-1.0)
    assert b.allow_entry() is False
    assert b.effective_min_score() >= 0.75
    assert b.snapshot().sleeping is True


def test_breaker_win_resets_streak():
    b = DrawdownCircuitBreaker(loss_streak=3, sleep_seconds=1.0)
    b.record_closed_pnl(-1.0)
    b.record_closed_pnl(-1.0)
    b.record_closed_pnl(2.0)
    assert b.snapshot().consecutive_losses == 0


def test_impact_cap_shrinks_on_thin_book():
    n = impact_capped_notional(
        desired_usdt=30.0, visible_depth_usdt=50.0, max_book_fraction=0.08,
        min_order_usdt=5.0, max_order_usdt=25.0,
    )
    assert n == 0.0
    n2 = impact_capped_notional(
        desired_usdt=30.0, visible_depth_usdt=500.0, max_book_fraction=0.08,
        min_order_usdt=5.0, max_order_usdt=25.0,
    )
    assert 5.0 <= n2 <= 25.0
