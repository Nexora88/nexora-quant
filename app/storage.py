"""SQLite persistence with in-memory buffer and background batch flushes.

Hot path (engine) only touches memory + a lock-free-ish queue; WAL SQLite is
updated on a timer or when the batch is full — reducing write-lock contention
with concurrent API reads.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any


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
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA busy_timeout = 30000")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA synchronous = NORMAL")
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
        while not self._stop.wait(self._flush_interval_s):
            try:
                self.flush()
            except Exception:
                pass

    def flush(self) -> None:
        with self._lock:
            states = dict(self._pending_states)
            trades = list(self._pending_trades)
            self._pending_states.clear()
            self._pending_trades.clear()
            trade_keys = set(self._pending_trade_keys)
            self._pending_trade_keys.clear()
        if not states and not trades:
            return
        with self._lock, self._db:
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
                trade_keys.discard(event_key)

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
        try:
            self.flush()
        except Exception:
            pass
        with self._lock:
            self._db.close()

    def __enter__(self) -> "PaperStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
