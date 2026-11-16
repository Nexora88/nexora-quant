#!/usr/bin/env python3
"""Verify a real paper session before allowing a mainnet go-live stamp.

A successful arithmetic smoke test is not an overnight run. This check requires
durable session telemetry, a minimum runtime/tick count, enough closed trades,
and positive fee-net PnL from the paper ledger.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from math import isfinite
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv()


def _parse_time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(os.getenv("PAPER_DB_PATH", "data/paper.sqlite3")))
    parser.add_argument("--min-hours", type=float, default=48.0)
    parser.add_argument("--min-ticks", type=int, default=1000)
    parser.add_argument("--min-closed-trades", type=int, default=20)
    parser.add_argument("--max-stale-minutes", type=float, default=120.0)
    args = parser.parse_args()

    failures: list[str] = []
    if args.min_hours <= 0 or args.min_ticks < 1 or args.min_closed_trades < 1:
        parser.error("minimum duration, ticks, and closed trades must be positive")
    if not args.db.is_file():
        print(f"FAIL paper database not found: {args.db}")
        return 1

    try:
        session_start: datetime | None = None
        session_end: datetime | None = None
        with sqlite3.connect(str(args.db)) as db:
            db.row_factory = sqlite3.Row
            session = db.execute(
                """SELECT * FROM paper_sessions WHERE mode='paper'
                   ORDER BY started_at DESC LIMIT 1"""
            ).fetchone()
            if session is None:
                failures.append("no durable paper session telemetry found")
                rows = []
            else:
                now = datetime.now(timezone.utc)
                session_start = _parse_time(session["started_at"])
                last_seen = _parse_time(session["last_seen_at"])
                ended_at = _parse_time(session["ended_at"]) if session["ended_at"] else None
                session_end = ended_at or now
                freshness_time = ended_at or last_seen
                duration_hours = max(0.0, (session_end - session_start).total_seconds() / 3600.0)
                stale_minutes = max(0.0, (now - freshness_time).total_seconds() / 60.0)
                print(
                    f"INFO session={session['session_id']} duration={duration_hours:.2f}h "
                    f"ticks={session['ticks']} reconnects={session['reconnects']} "
                    f"stale={stale_minutes:.1f}m"
                )
                if duration_hours < args.min_hours:
                    failures.append(f"paper session lasted {duration_hours:.2f}h; need {args.min_hours:.2f}h")
                if int(session["ticks"]) < args.min_ticks:
                    failures.append(f"only {session['ticks']} primary ticks; need {args.min_ticks}")
                if stale_minutes > args.max_stale_minutes:
                    failures.append(f"paper session telemetry is stale ({stale_minutes:.1f} minutes)")
                rows = db.execute(
                    "SELECT trade_json, created_at FROM paper_trades ORDER BY id ASC"
                ).fetchall()

        closed: list[float] = []
        incomplete = 0
        for row in rows:
            created_at = _parse_time(row["created_at"])
            if session_start is None or session_end is None or not session_start <= created_at <= session_end:
                continue
            trade = json.loads(row["trade_json"])
            if str(trade.get("side", "")).lower() not in {"sell", "short"}:
                continue
            if trade.get("accounting_complete") is not True or trade.get("pnl_usdt") is None:
                incomplete += 1
                continue
            pnl = float(trade["pnl_usdt"])
            if not isfinite(pnl):
                incomplete += 1
                continue
            closed.append(pnl)

        if incomplete:
            failures.append(f"{incomplete} closed trades lack verified fee-complete accounting")
        if len(closed) < args.min_closed_trades:
            failures.append(f"only {len(closed)} fee-complete closed trades; need {args.min_closed_trades}")
        total_net = sum(closed)
        expectancy = total_net / len(closed) if closed else 0.0
        print(
            f"INFO closed_trades={len(closed)} fee_net_total={total_net:.6f} "
            f"fee_net_expectancy={expectancy:.6f} USDT/trade"
        )
        if not closed or total_net <= 0 or expectancy <= 0:
            failures.append("paper closed-trade fee-net expectancy is not positive")

    except (sqlite3.Error, OSError, ValueError, TypeError, KeyError) as exc:
        failures.append(f"could not verify paper evidence: {exc}")

    print(f"INFO checked_at={datetime.now(timezone.utc).isoformat()}")
    if failures:
        print("OVERNIGHT_CHECK_FAIL")
        for failure in failures:
            print(f" - {failure}")
        return 1

    print("OVERNIGHT_CHECK_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
