import pytest
from dataclasses import replace

from app import engine_loop
from app.engine_tick import handle_tick


@pytest.mark.asyncio
async def test_engine_loop_rejects_non_paper_mode_before_executor_creation(monkeypatch):
    monkeypatch.setattr(engine_loop, "settings", replace(engine_loop.settings, trading_mode="live"))

    def forbidden_executor_creation():
        pytest.fail("executor must not be created outside paper mode")

    monkeypatch.setattr(engine_loop.es, "_build_executor", forbidden_executor_creation)

    with pytest.raises(RuntimeError, match="restricted to paper mode"):
        await engine_loop.run()


@pytest.mark.asyncio
async def test_handle_tick_rejects_non_paper_mode_before_processing():
    with pytest.raises(RuntimeError, match="restricted to paper mode"):
        await handle_tick(
            depth=None,
            store=None,
            history=None,
            features=None,
            mode="live",
            key="test",
            persist=lambda: None,
            confirmations=0,
            ticks=0,
        )
