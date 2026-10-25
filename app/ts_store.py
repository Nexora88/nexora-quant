"""Columnar-ish research store for L2 features (stdlib + optional rotation).

JSONL.gz remains the capture format. This module packs periodic feature rows into
a compact SQLite table (time-series friendly indexes) so multi-day analysis does
not require scanning entire gzip archives. For production TB-scale workloads,
export these rows to ClickHouse / Parquet externally.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class FeatureTimeSeriesStore:
    def __init__(self, path: str | Path = "data/features.sqlite3") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, timeout=30.0, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS l2_features (
                ts_ns INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                mid REAL,
                spread_bps REAL,
                imbalance REAL,
                momentum_bps REAL,
                score REAL,
                bid REAL,
                ask REAL,
                extra_json TEXT,
                PRIMARY KEY (symbol, ts_ns)
            );
            CREATE INDEX IF NOT EXISTS idx_l2_features_ts ON l2_features(ts_ns);
            """
        )
        self._db.commit()
        self._buffer: list[tuple] = []
        self._buf_limit = 64

    def append(
        self,
        *,
        ts_ns: int,
        symbol: str,
        mid: float | None,
        spread_bps: float | None,
        imbalance: float | None,
        momentum_bps: float | None,
        score: float | None,
        bid: float | None,
        ask: float | None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        row = (
            int(ts_ns),
            symbol.lower(),
            mid,
            spread_bps,
            imbalance,
            momentum_bps,
            score,
            bid,
            ask,
            json.dumps(extra or {}, separators=(",", ":")),
        )
        with self._lock:
            self._buffer.append(row)
            if len(self._buffer) >= self._buf_limit:
                self._flush_unlocked()

    def _flush_unlocked(self) -> None:
        if not self._buffer:
            return
        self._db.executemany(
            """INSERT OR REPLACE INTO l2_features
               (ts_ns,symbol,mid,spread_bps,imbalance,momentum_bps,score,bid,ask,extra_json)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            self._buffer,
        )
        self._db.commit()
        self._buffer.clear()

    def flush(self) -> None:
        with self._lock:
            self._flush_unlocked()

    def query(
        self,
        symbol: str,
        *,
        start_ns: int | None = None,
        end_ns: int | None = None,
        limit: int = 10_000,
    ) -> list[dict[str, Any]]:
        self.flush()
        clauses = ["symbol=?"]
        params: list[Any] = [symbol.lower()]
        if start_ns is not None:
            clauses.append("ts_ns>=?")
            params.append(start_ns)
        if end_ns is not None:
            clauses.append("ts_ns<=?")
            params.append(end_ns)
        params.append(limit)
        sql = f"SELECT * FROM l2_features WHERE {' AND '.join(clauses)} ORDER BY ts_ns LIMIT ?"
        with self._lock:
            rows = self._db.execute(sql, params).fetchall()
        cols = [d[0] for d in self._db.execute("SELECT * FROM l2_features LIMIT 0").description]
        return [dict(zip(cols, row)) for row in rows]

    def close(self) -> None:
        self.flush()
        with self._lock:
            self._db.close()
