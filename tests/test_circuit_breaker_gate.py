from app.circuit_breaker import DrawdownCircuitBreaker


def test_breaker_elevates_and_sleeps() -> None:
    cb = DrawdownCircuitBreaker(loss_streak=3, base_min_score=0.2, elevated_min_score=0.5, sleep_seconds=60)
    assert cb.allow_entry()
    assert cb.effective_min_score() == 0.2
    cb.record_closed_pnl(-1.0)
    cb.record_closed_pnl(-1.0)
    assert cb.effective_min_score() >= 0.2
    cb.record_closed_pnl(-1.0)
    assert not cb.allow_entry() or cb.snapshot().sleeping
    cb.record_closed_pnl(1.0)
