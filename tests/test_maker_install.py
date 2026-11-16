import pytest

from app.live import LiveExecutor
from app.live_maker import install_buy_limit, install_maker_entry


def test_live_maker_install_is_disabled():
    assert install_maker_entry is install_buy_limit
    with pytest.raises(RuntimeError, match="Live maker orders are disabled"):
        install_buy_limit(LiveExecutor)
