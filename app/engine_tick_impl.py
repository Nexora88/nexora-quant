"""Shim — handle_tick is defined in app.engine_tick (monolithic)."""
from app.engine_tick import handle_tick  # noqa: F401

__all__ = ["handle_tick"]
