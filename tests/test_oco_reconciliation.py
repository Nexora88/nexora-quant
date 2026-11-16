"""Live OCO reconciliation is disabled; paper executor never calls exchange APIs."""
import pytest

from app.live import LiveExecutor


def test_live_oco_reconciliation_cannot_be_instantiated():
    with pytest.raises(RuntimeError, match="LiveExecutor is disabled"):
        LiveExecutor(object(), symbol="BTCUSDT", fee_rate=0.001)
