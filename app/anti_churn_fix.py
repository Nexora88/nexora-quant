"""Ensure hourly_trade_ts is only written by record_fill (buy side).

Historically engine_tick also appended after record_fill → paper counted 2x.
Import this once at setup; it is a no-op guard + documentation anchor.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_PATCHED = False


def ensure_single_source_hourly() -> None:
    """Log once; actual fix is in engine_tick (no manual append after record_fill)."""
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True
    log.info("anti_churn: hourly_trade_ts single-source = RuntimeState.record_fill")
