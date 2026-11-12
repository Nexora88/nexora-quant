"""Primary symbol may change only when the desk is flat."""


def can_switch_primary(*, base_quantity: float, candidate: str, current: str) -> bool:
    """Engine rule: never rotate the trading symbol while holding inventory."""
    if not candidate or candidate == current:
        return False
    return float(base_quantity or 0.0) <= 0.0


def test_switch_blocked_when_in_position():
    assert not can_switch_primary(base_quantity=0.01, candidate="ethusdt", current="btcusdt")


def test_switch_allowed_when_flat():
    assert can_switch_primary(base_quantity=0.0, candidate="ethusdt", current="btcusdt")


def test_no_switch_same_symbol():
    assert not can_switch_primary(base_quantity=0.0, candidate="btcusdt", current="btcusdt")
