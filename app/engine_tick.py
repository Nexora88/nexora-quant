"""Per-depth-tick entrypoint — body lives in engine_tick_impl for maintainability."""
from app.engine_tick_impl import handle_tick  # noqa: F401

__all__ = ["handle_tick"]
