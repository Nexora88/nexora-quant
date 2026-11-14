"""PREFER_MAKER must install buy_limit; broken import must hard-fail."""
from __future__ import annotations

from app.live import LiveExecutor
from app.live_maker import install_buy_limit, install_maker_entry


def test_install_buy_limit_attaches_method() -> None:
    class _Tmp:
        pass

    install_buy_limit(_Tmp)  # type: ignore[arg-type]
    assert hasattr(_Tmp, "buy_limit")


def test_install_maker_entry_alias() -> None:
    assert install_maker_entry is install_buy_limit


def test_live_executor_accepts_buy_limit() -> None:
    install_buy_limit(LiveExecutor)
    assert callable(getattr(LiveExecutor, "buy_limit", None))
