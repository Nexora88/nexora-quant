"""Trading engine entrypoint — delegates to engine_core for the full loop."""
from __future__ import annotations

import logging

from app.engine_core import run as run_core
from app.engine_core import state, risk  # re-export for api

log = logging.getLogger(__name__)

__all__ = ["run", "state", "risk"]


async def run() -> None:
    """Start the synchronized depth trading loop (paper or live)."""
    await run_core()
