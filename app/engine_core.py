"""Compatibility: re-export run and state from split modules."""
from app.engine_setup import state, risk, executor  # noqa: F401
from app.engine_loop import run

__all__ = ["run", "state", "risk", "executor"]
