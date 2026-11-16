"""SQLite persistence with in-memory buffer and background batch flushes.

Hot path (engine) only touches memory + a lock-free-ish queue; WAL SQLite is
updated on a timer or when the batch is full — reducing write-lock contention
with concurrent API reads.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from collections import deque
from pathlib import Path
from typing import Any

from app.sqlite_util import configure_sqlite


class PaperStore:
    """Persist paper snapshots and trades; never stores exchange credentials."""

    def __init__(
        self,
        path: str | Path = "data/paper.sqlite3",
        *,
        batch_size: int = 32,
        flush_interval_s: float = 0.5,
        async_writes: bool = True,
    ) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, timeout=30.0, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        configure_sqlite(self._db)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS paper_state (
                state_key TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT UNIQUE,
                trade_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS paper_sessions (
                session_id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                started_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                ended_at TEXT,
                ticks INTEGER NOT NULL DEFAULT 0,
                reconnects INTEGER NOT NULL DEFAULT 0,
                trade_count INTEGER NOT NULL DEFAULT 0,
                realized_pnl_usdt REAL NOT NULL DEFAULT 0
            );
            """
        )
        self._db.commit()
        self._batch_size = max(1, batch_size)
        self._flush_interval_s = max(0.05, flush_interval_s)
        self._async_writes = async_writes
        self._pending_states: dict[str, str] = {}
        self._pending_trades: deque[tuple[str, str]] = deque()
        self._pending_trade_keys: set[str] = set()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        if async_writes and self.path != ":memory:":
            self._worker = threading.Thread(target=self._flush_loop, name="paper-store-flush", daemon=True)
            self._worker.start()

    def _flush_loop(self) -> None:
        import logging

        log = logging.getLogger(__name__)
        while not self._stop.wait(self._flush_interval_s):
            try:
                self.flush()
            except Exception:
                # Keep the in-memory batch queued for retry and make durability
                # failures visible instead of silently discarding ledger writes.
                log.exception("PaperStore background flush failed; batch retained")

    def flush(self) -> None:
        # Keep pending records in memory until the SQLite transaction commits.
        # The lock prevents concurrent enqueue operations while this batch commits.
        with self._lock:
            states = dict(self._pending_states)
            trades = list(self._pending_trades)
            if not states and not trades:
                return
            with self._db:
                for key, payload in states.items():
                    self._db.execute(
                        """INSERT INTO paper_state(state_key,state_json,updated_at)
                           VALUES(?,?,CURRENT_TIMESTAMP)
                           ON CONFLICT(state_key) DO UPDATE SET
                           state_json=excluded.state_json, updated_at=CURRENT_TIMESTAMP""",
                        (key, payload),
                    )
                for event_key, payload in trades:
                    self._db.execute(
                        "INSERT OR IGNORE INTO paper_trades(event_key,trade_json) VALUES(?,?)",
                        (event_key, payload),
                    )
            # The transaction committed successfully; now and only now clear
            # exactly the records included in it.
            for key, payload in states.items():
                if self._pending_states.get(key) == payload:
                    self._pending_states.pop(key, None)
            committed_keys = {event_key for event_key, _ in trades}
            self._pending_trades = deque(
                (event_key, payload)
                for event_key, payload in self._pending_trades
                if event_key not in committed_keys
            )
            self._pending_trade_keys.difference_update(committed_keys)

    def save_state(self, key: str, state: dict[str, Any]) -> None:
        if not key:
            raise ValueError("state key is required")
        payload = json.dumps(state, separators=(",", ":"), sort_keys=True, allow_nan=False)
        if not self._async_writes:
            with self._lock, self._db:
                self._db.execute(
                    """INSERT INTO paper_state(state_key,state_json,updated_at)
                       VALUES(?,?,CURRENT_TIMESTAMP)
                       ON CONFLICT(state_key) DO UPDATE SET
                       state_json=excluded.state_json, updated_at=CURRENT_TIMESTAMP""",
                    (key, payload),
                )
            return
        with self._lock:
            self._pending_states[key] = payload
        if len(self._pending_states) + len(self._pending_trades) >= self._batch_size:
            self.flush()

    def load_state(self, key: str) -> dict[str, Any] | None:
        self.flush()
        with self._lock:
            if key in self._pending_states:
                return json.loads(self._pending_states[key])
            row = self._db.execute(
                "SELECT state_json FROM paper_state WHERE state_key=?", (key,)
            ).fetchone()
        return json.loads(row["state_json"]) if row else None

    def append_trade(self, trade: dict[str, Any], *, event_key: str) -> bool:
        if not event_key:
            raise ValueError("event_key is required for idempotency")
        payload = json.dumps(trade, separators=(",", ":"), sort_keys=True, allow_nan=False)
        if not self._async_writes:
            with self._lock, self._db:
                cursor = self._db.execute(
                    "INSERT OR IGNORE INTO paper_trades(event_key,trade_json) VALUES(?,?)",
                    (event_key, payload),
                )
            return cursor.rowcount == 1
        with self._lock:
            if event_key in self._pending_trade_keys:
                return False
            row = self._db.execute(
                "SELECT 1 FROM paper_trades WHERE event_key=? LIMIT 1", (event_key,)
            ).fetchone()
            if row:
                return False
            self._pending_trade_keys.add(event_key)
            self._pending_trades.append((event_key, payload))
            should_flush = len(self._pending_trades) >= self._batch_size
        if should_flush:
            self.flush()
        return True

    def list_trades(self, *, limit: int = 100, before_id: int | None = None) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        self.flush()
        with self._lock:
            if before_id is None:
                rows = self._db.execute(
                    "SELECT id, event_key, trade_json, created_at FROM paper_trades ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = self._db.execute(
                    """SELECT id, event_key, trade_json, created_at FROM paper_trades
                       WHERE id < ? ORDER BY id DESC LIMIT ?""",
                    (before_id, limit),
                ).fetchall()
        return [
            {
                "id": row["id"],
                "event_key": row["event_key"],
                "trade": json.loads(row["trade_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def close(self) -> None:
        self._stop.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2.0)
        # Do not close the connection or suppress the error if durability fails:
        # callers must see that queued ledger writes were not committed.
        self.flush()
        with self._lock:
            self._db.close()

    def __enter__(self) -> "PaperStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def start_session(self, session_id: str, mode: str) -> None:
        if not session_id or mode not in {"paper", "live"}:
            raise ValueError("valid session_id and trading mode are required")
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO paper_sessions
                   (session_id, mode, started_at, last_seen_at)
                   VALUES (?, ?, ?, ?)""",
                (session_id, mode, now, now),
            )

    def heartbeat_session(
        self, session_id: str, *, ticks: int, reconnects: int,
        trade_count: int, realized_pnl_usdt: float,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._db:
            cursor = self._db.execute(
                """UPDATE paper_sessions SET last_seen_at=?, ticks=?,
                   reconnects=?, trade_count=?, realized_pnl_usdt=?
                   WHERE session_id=?""",
                (now, max(0, int(ticks)), max(0, int(reconnects)),
                 max(0, int(trade_count)), float(realized_pnl_usdt), session_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown paper session: {session_id}")

    def end_session(
        self, session_id: str, *, ticks: int, reconnects: int,
        trade_count: int, realized_pnl_usdt: float,
    ) -> None:
        self.heartbeat_session(
            session_id, ticks=ticks, reconnects=reconnects,
            trade_count=trade_count, realized_pnl_usdt=realized_pnl_usdt,
        )
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._db:
            self._db.execute(
                "UPDATE paper_sessions SET ended_at=? WHERE session_id=?",
                (now, session_id),
            )

    def latest_session(self, mode: str = "paper") -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                """SELECT * FROM paper_sessions WHERE mode=?
                   ORDER BY started_at DESC LIMIT 1""",
                (mode,),
            ).fetchone()
        return dict(row) if row else None
