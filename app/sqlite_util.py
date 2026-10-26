"""Shared SQLite connection pragmas: WAL + busy timeout for concurrent readers/writers.

WAL allows one writer and many readers without the default exclusive lock storms
that cause ``database is locked`` under AsyncIoQueue + FastAPI snapshot load.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)


def configure_sqlite(
    db: sqlite3.Connection,
    *,
    busy_timeout_ms: int = 30_000,
    synchronous: str = "NORMAL",
) -> str:
    """Apply production-safe pragmas. Returns resolved journal_mode (expect ``wal``)."""
    db.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    db.execute("PRAGMA foreign_keys = ON")
    row = db.execute("PRAGMA journal_mode = WAL").fetchone()
    mode = str(row[0]).lower() if row else "unknown"
    if mode != "wal":
        log.warning("SQLite journal_mode=%s (wanted wal); concurrent reads may block writes", mode)
    else:
        log.debug("SQLite journal_mode=WAL")
    # NORMAL is durable enough with WAL; FULL is slower under high write rate.
    db.execute(f"PRAGMA synchronous = {synchronous}")
    return mode


def connect_sqlite(
    path: str,
    *,
    timeout: float = 30.0,
    check_same_thread: bool = False,
    row_factory: Any = None,
) -> sqlite3.Connection:
    """Open connection and force WAL mode."""
    db = sqlite3.connect(path, timeout=timeout, check_same_thread=check_same_thread)
    if row_factory is not None:
        db.row_factory = row_factory
    configure_sqlite(db)
    return db
