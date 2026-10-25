import pytest
from app.config import Settings

def test_live_mode_is_rejected():
    with pytest.raises(ValueError, match="Only TRADING_MODE=paper"):
        Settings(trading_mode="live").validate()

def test_order_size_cannot_exceed_maximum():
    with pytest.raises(ValueError, match="cannot exceed"):
        Settings(order_size_usdt=100, max_order_size_usdt=50).validate()
