"""Deprecated: anti-churn + maker metrics are permanent in engine_tick.py.

Kept as a no-op so old import paths do not crash.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def apply() -> bool:
    log.debug("anti-churn apply is a no-op; engine_tick is patched in-repo")
    return False
