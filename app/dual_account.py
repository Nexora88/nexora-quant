"""Account-isolated ledgers, versioned strategy knowledge and reconciliation.

This module is deliberately an infrastructure boundary: it never submits orders.
Execution processes must use distinct account_id values and call these APIs from
their own fill/close/reconciliation paths. Strategy candidates contain only
bounded strategy parameters; money, positions and hard risk controls are excluded.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from app.sqlite_util import configure_sqlite

LEARNABLE_PARAMETERS = frozenset({
    "entry_min_score", "size_bias", "tp_scale", "compound_fraction",
})
FORBIDDEN_PARAMETERS = frozenset({
    "max_order_size_usdt", "max_daily_loss_usdt", "max_daily_fee_usdt",
    "risk_per_trade_pct", "stop_loss_pct", "take_profit_pct",
    "trailing_stop_pct", "kill_switch", "max_concurrent_positions",
})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finite(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


class DualAccountStore:
    """One durable store with hard account_id partitioning for paper and live."""

    def __init__(self, path: str | Path = "data/dual-account.sqlite3") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        configure_sqlite(self.db)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
                account_id TEXT PRIMARY KEY,
                mode TEXT NOT NULL CHECK(mode IN ('paper','live')),
                created_at TEXT NOT NULL,
                initial_cash_usdt REAL NOT NULL CHECK(initial_cash_usdt > 0)
            );
            DROP INDEX IF EXISTS one_account_per_mode;
            CREATE UNIQUE INDEX IF NOT EXISTS one_paper_account
                ON accounts(mode) WHERE mode='paper';
            CREATE TABLE IF NOT EXISTS account_events (
                event_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES accounts(account_id),
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS account_events_by_account
                ON account_events(account_id, created_at);
            CREATE TABLE IF NOT EXISTS learner_states (
                account_id TEXT PRIMARY KEY REFERENCES accounts(account_id),
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS strategy_versions (
                version_id TEXT PRIMARY KEY,
                source_account_id TEXT NOT NULL REFERENCES accounts(account_id),
                parameters_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS strategy_assignments (
                target_account_id TEXT PRIMARY KEY REFERENCES accounts(account_id),
                version_id TEXT NOT NULL REFERENCES strategy_versions(version_id),
                previous_version_id TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reconciliation_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL REFERENCES accounts(account_id),
                status TEXT NOT NULL,
                differences_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        self.db.commit()

    def register_account(self, account_id: str, mode: str, initial_cash_usdt: float) -> None:
        account_id = str(account_id).strip()
        mode = str(mode).strip().lower()
        cash = _finite(initial_cash_usdt, "initial_cash_usdt")
        if not account_id or mode not in {"paper", "live"} or cash <= 0:
            raise ValueError("account_id, paper/live mode and positive cash are required")
        with self.db:
            existing = self.db.execute(
                "SELECT account_id FROM accounts WHERE mode='paper'"
            ).fetchone() if mode == "paper" else None
            if existing and existing["account_id"] != account_id:
                raise ValueError("the paper account is already registered")
            self.db.execute(
                """INSERT INTO accounts(account_id,mode,created_at,initial_cash_usdt)
                   VALUES(?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET
                   mode=excluded.mode, initial_cash_usdt=excluded.initial_cash_usdt""",
                (account_id, mode, _utc_now(), cash),
            )

    def account(self, account_id: str) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT * FROM accounts WHERE account_id=?", (account_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown account: {account_id}")
        return dict(row)

    def record_event(
        self, account_id: str, event_type: str, payload: Mapping[str, Any],
        *, event_id: str | None = None,
    ) -> bool:
        self.account(account_id)
        event_id = event_id or str(uuid.uuid4())
        if not event_type.strip():
            raise ValueError("event_type is required")
        encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self.db:
            cur = self.db.execute(
                """INSERT OR IGNORE INTO account_events
                   (event_id,account_id,event_type,payload_json,created_at)
                   VALUES(?,?,?,?,?)""",
                (event_id, account_id, event_type, encoded, _utc_now()),
            )
        return cur.rowcount == 1

    def save_learner_state(self, account_id: str, state: Mapping[str, Any]) -> None:
        self.account(account_id)
        encoded = json.dumps(dict(state), sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self.db:
            self.db.execute(
                """INSERT INTO learner_states(account_id,state_json,updated_at)
                   VALUES(?,?,?) ON CONFLICT(account_id) DO UPDATE SET
                   state_json=excluded.state_json, updated_at=excluded.updated_at""",
                (account_id, encoded, _utc_now()),
            )

    def load_learner_state(self, account_id: str) -> dict[str, Any] | None:
        self.account(account_id)
        row = self.db.execute(
            "SELECT state_json FROM learner_states WHERE account_id=?", (account_id,)
        ).fetchone()
        return json.loads(row["state_json"]) if row else None

    def publish_paper_candidate(
        self, source_account_id: str, parameters: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> str:
        source = self.account(source_account_id)
        if source["mode"] != "paper":
            raise ValueError("strategy candidates must originate from the paper account")
        keys = set(parameters)
        if not keys or not keys <= LEARNABLE_PARAMETERS:
            forbidden = sorted(keys - LEARNABLE_PARAMETERS)
            raise ValueError(f"candidate contains unsupported or hard-risk parameters: {forbidden}")
        clean_params = {k: _finite(v, k) for k, v in parameters.items()}
        bounds = {
            "entry_min_score": (0.22, 0.65),
            "size_bias": (0.4, 1.6),
            "tp_scale": (0.55, 1.25),
            "compound_fraction": (0.05, 0.95),
        }
        for key, value in clean_params.items():
            low, high = bounds[key]
            if not low <= value <= high:
                raise ValueError(f"candidate parameter {key} must be within [{low}, {high}]")
        required = {
            "closed_trades": 50, "oos_windows": 4, "positive_oos_windows": 3,
        }
        for key, minimum in required.items():
            if int(evidence.get(key, -1)) < minimum:
                raise ValueError(f"candidate evidence requires {key}>={minimum}")
        if _finite(evidence.get("fee_net_expectancy_usdt"), "fee_net_expectancy_usdt") <= 0:
            raise ValueError("candidate fee-net expectancy must be positive")
        if not 0 <= _finite(evidence.get("max_drawdown_pct"), "max_drawdown_pct") < 8:
            raise ValueError("candidate max drawdown must be in [0,8)")
        if int(evidence.get("data_gaps", -1)) != 0 or int(evidence.get("ledger_gaps", -1)) != 0:
            raise ValueError("candidate evidence must have zero data and ledger gaps")
        evidence_copy = dict(evidence)
        params_json = json.dumps(clean_params, sort_keys=True, separators=(",", ":"), allow_nan=False)
        evidence_json = json.dumps(evidence_copy, sort_keys=True, separators=(",", ":"), allow_nan=False)
        fingerprint = hashlib.sha256((params_json + evidence_json).encode()).hexdigest()
        version_id = f"strategy-{uuid.uuid4().hex[:12]}"
        with self.db:
            self.db.execute(
                """INSERT INTO strategy_versions
                   (version_id,source_account_id,parameters_json,evidence_json,fingerprint,created_at)
                   VALUES(?,?,?,?,?,?)""",
                (version_id, source_account_id, params_json, evidence_json, fingerprint, _utc_now()),
            )
        return version_id

    def promote_candidate(
        self, version_id: str, target_account_id: str, *, operator_approved: bool = False,
    ) -> dict[str, Any]:
        target = self.account(target_account_id)
        if target["mode"] != "live":
            raise ValueError("paper candidates may only be promoted to the live account")
        if operator_approved is not True:
            raise PermissionError("explicit operator approval is required")
        version = self.db.execute(
            "SELECT * FROM strategy_versions WHERE version_id=?", (version_id,)
        ).fetchone()
        if version is None:
            raise KeyError(f"unknown strategy version: {version_id}")
        params = json.loads(version["parameters_json"])
        if not set(params) <= LEARNABLE_PARAMETERS:
            raise ValueError("stored strategy version attempts to change protected settings")
        with self.db:
            previous = self.db.execute(
                "SELECT version_id FROM strategy_assignments WHERE target_account_id=?",
                (target_account_id,),
            ).fetchone()
            previous_id = previous["version_id"] if previous else None
            self.db.execute(
                """INSERT INTO strategy_assignments
                   (target_account_id,version_id,previous_version_id,updated_at)
                   VALUES(?,?,?,?) ON CONFLICT(target_account_id) DO UPDATE SET
                   previous_version_id=excluded.previous_version_id,
                   version_id=excluded.version_id, updated_at=excluded.updated_at""",
                (target_account_id, version_id, previous_id, _utc_now()),
            )
        return {"version_id": version_id, "previous_version_id": previous_id, "parameters": params}

    def rollback_strategy(self, target_account_id: str) -> str:
        target = self.account(target_account_id)
        if target["mode"] != "live":
            raise ValueError("strategy rollback target must be the live account")
        row = self.db.execute(
            """SELECT version_id,previous_version_id FROM strategy_assignments
               WHERE target_account_id=?""", (target_account_id,)
        ).fetchone()
        if row is None or not row["previous_version_id"]:
            raise ValueError("no previous strategy version is available")
        with self.db:
            self.db.execute(
                """UPDATE strategy_assignments SET version_id=?, previous_version_id=NULL,
                   updated_at=? WHERE target_account_id=?""",
                (row["previous_version_id"], _utc_now(), target_account_id),
            )
        return str(row["previous_version_id"])

    def active_strategy(self, target_account_id: str) -> dict[str, Any] | None:
        self.account(target_account_id)
        row = self.db.execute(
            """SELECT v.* FROM strategy_assignments a
               JOIN strategy_versions v ON v.version_id=a.version_id
               WHERE a.target_account_id=?""", (target_account_id,)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["parameters"] = json.loads(result.pop("parameters_json"))
        result["evidence"] = json.loads(result.pop("evidence_json"))
        return result

    def reconcile(
        self, account_id: str, local: Mapping[str, Any], exchange: Mapping[str, Any],
        *, tolerances: Mapping[str, float] | None = None,
    ) -> dict[str, Any]:
        account = self.account(account_id)
        if account["mode"] != "live":
            raise ValueError("exchange reconciliation applies only to the live account")
        tolerances = dict(tolerances or {
            "cash_usdt": 0.01,
            "base_quantity": 1e-8,
            "fees_usdt": 0.01,
            "open_order_count": 0.0,
            "unmatched_exchange_order_count": 0.0,
            "unmatched_local_order_count": 0.0,
            "unknown_open_order_count": 0.0,
            "unpriced_commission_count": 0.0,
        })
        differences: dict[str, dict[str, float]] = {}
        for key, tolerance in tolerances.items():
            left = _finite(local.get(key, 0), f"local.{key}")
            right = _finite(exchange.get(key, 0), f"exchange.{key}")
            delta = left - right
            if abs(delta) > float(tolerance):
                differences[key] = {
                    "local": left, "exchange": right, "delta": delta,
                    "tolerance": float(tolerance),
                }
        status = "pass" if not differences else "mismatch"
        with self.db:
            self.db.execute(
                """INSERT INTO reconciliation_runs(account_id,status,differences_json,created_at)
                   VALUES(?,?,?,?)""",
                (account_id, status, json.dumps(differences, sort_keys=True), _utc_now()),
            )
        return {"account_id": account_id, "status": status, "differences": differences}

    def close(self) -> None:
        self.db.close()


class ReconciliationMonitor:
    """Periodic fail-closed reconciliation; callback should activate the live kill switch."""

    def __init__(
        self, store: DualAccountStore, account_id: str,
        snapshot_provider: Callable[[], Awaitable[tuple[Mapping[str, Any], Mapping[str, Any]]]],
        on_mismatch: Callable[[dict[str, Any]], Any], *, interval_seconds: float = 30.0,
    ) -> None:
        if interval_seconds < 1:
            raise ValueError("reconciliation interval must be at least one second")
        self.store = store
        self.account_id = account_id
        self.snapshot_provider = snapshot_provider
        self.on_mismatch = on_mismatch
        self.interval_seconds = interval_seconds

    async def run_once(self) -> dict[str, Any]:
        local, exchange = await self.snapshot_provider()
        result = self.store.reconcile(self.account_id, local, exchange)
        if result["status"] != "pass":
            self.on_mismatch(result)
        return result

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.on_mismatch({
                    "account_id": self.account_id, "status": "error",
                    "differences": {"reconciliation_error": str(exc)},
                })
            await asyncio.sleep(self.interval_seconds)

class AccountLearningCoordinator:
    """Persist one OnlineLearner per account; live learns only confirmed closes."""

    def __init__(self, store: DualAccountStore, account_id: str, mode: str, learner: Any) -> None:
        account = store.account(account_id)
        if account["mode"] != mode:
            raise ValueError("learner mode does not match its account")
        self.store = store
        self.account_id = account_id
        self.mode = mode
        self.learner = learner

    def restore(self) -> bool:
        state = self.store.load_learner_state(self.account_id)
        if not state:
            return False
        self.learner.load_state(state)
        return True

    def persist(self) -> None:
        self.store.save_learner_state(self.account_id, self.learner.export_state())

    def record_closed_trade(
        self, pnl_usdt: float, *, event_id: str, regime: str = "unknown",
        reason: str = "", accounting_complete: bool, exchange_confirmed: bool,
    ) -> bool:
        if not accounting_complete:
            return False
        if self.mode == "live" and not exchange_confirmed:
            raise ValueError("live learning requires an exchange-confirmed close")
        pnl = _finite(pnl_usdt, "pnl_usdt")
        previous = self.learner.export_state()
        self.learner.record_trade(pnl, regime=regime, reason=reason)
        state_json = json.dumps(
            self.learner.export_state(), sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        payload = json.dumps(
            {"pnl_usdt": pnl, "regime": regime, "reason": reason,
             "accounting_complete": True, "exchange_confirmed": bool(exchange_confirmed)},
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        try:
            with self.store.db:
                inserted = self.store.db.execute(
                    """INSERT OR IGNORE INTO account_events
                       (event_id,account_id,event_type,payload_json,created_at)
                       VALUES(?,?,?,?,?)""",
                    (event_id, self.account_id, "closed_trade", payload, _utc_now()),
                ).rowcount
                if not inserted:
                    self.learner.load_state(previous)
                    return False
                self.store.db.execute(
                    """INSERT INTO learner_states(account_id,state_json,updated_at)
                       VALUES(?,?,?) ON CONFLICT(account_id) DO UPDATE SET
                       state_json=excluded.state_json, updated_at=excluded.updated_at""",
                    (self.account_id, state_json, _utc_now()),
                )
        except Exception:
            self.learner.load_state(previous)
            raise
        return True
