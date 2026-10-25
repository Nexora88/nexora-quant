"""Small SQLite store for paper-trading state and an append-only trade ledger."""
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class PaperStore:
    """Persist paper snapshots and trades; never stores exchange credentials."""

    def __init__(self, path: str | Path = "data/paper.sqlite3") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, timeout=10.0, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA busy_timeout = 10000")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript("""
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
        """)
        self._db.commit()

    def save_state(self, key: str, state: dict[str, Any]) -> None:
        if not key:
            raise ValueError("state key is required")
        payload = json.dumps(state, separators=(",", ":"), sort_keys=True, allow_nan=False)
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO paper_state(state_key,state_json,updated_at)
                   VALUES(?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(state_key) DO UPDATE SET
                   state_json=excluded.state_json, updated_at=CURRENT_TIMESTAMP""",
                (key, payload),
            )

    def load_state(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT state_json FROM paper_state WHERE state_key=?", (key,)
            ).fetchone()
        return json.loads(row["state_json"]) if row else None

    def append_trade(self, trade: dict[str, Any], *, event_key: str) -> bool:
        """Insert once by event_key; return False when replayed."""
        if not event_key:
            raise ValueError("event_key is required for idempotency")
        payload = json.dumps(trade, separators=(",", ":"), sort_keys=True, allow_nan=False)
        with self._lock, self._db:
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO paper_trades(event_key,trade_json) VALUES(?,?)",
                (event_key, payload),
            )
        return cursor.rowcount == 1

    def list_trades(self, *, limit: int = 100, before_id: int | None = None) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
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
            {"id": row["id"], "event_key": row["event_key"],
             "trade": json.loads(row["trade_json"]), "created_at": row["created_at"]}
            for row in rows
        ]

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> "PaperStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
