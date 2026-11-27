from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone

from app.storage import PaperStore


def make_paper_evidence(
    path, *, hours: int = 49, trades: int = 20, trade_age_hours: int = 0,
    reconnects: int = 0, heartbeat_minutes_ago: int = 0,
):
    with PaperStore(path, async_writes=False) as store:
        store.start_session("overnight-test", "paper")
        started = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        store._db.execute(
            """UPDATE paper_sessions SET started_at=?,
               ticks=2000, reconnects=?, trade_count=? WHERE session_id=?""",
            (started, reconnects, trades * 2, "overnight-test"),
        )
        for i in range(trades):
            store.append_trade(
                {
                    "side": "sell", "pnl_usdt": 0.05,
                    "accounting_complete": True,
                },
                event_key=f"closed-{i}",
            )
        if trade_age_hours:
            old_trade_time = (
                datetime.now(timezone.utc) - timedelta(hours=trade_age_hours)
            ).strftime("%Y-%m-%d %H:%M:%S")
            store._db.execute("UPDATE paper_trades SET created_at=?", (old_trade_time,))
        heartbeat = (datetime.now(timezone.utc) - timedelta(minutes=heartbeat_minutes_ago)).isoformat()
        store._db.execute("UPDATE paper_sessions SET last_seen_at=?", (heartbeat,))
        store._db.commit()


def run_check(path):
    return subprocess.run(
        [
            sys.executable, "scripts/overnight_paper_check.py",
            "--db", str(path), "--min-hours", "48",
            "--min-ticks", "1000", "--min-closed-trades", "20",
        ],
        capture_output=True, text=True, check=False,
    )


def test_overnight_check_requires_real_durable_session_and_fee_net_trades(tmp_path):
    db = tmp_path / "paper.sqlite3"
    make_paper_evidence(db)
    result = run_check(db)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OVERNIGHT_CHECK_PASS" in result.stdout


def test_overnight_check_rejects_short_session(tmp_path):
    db = tmp_path / "paper.sqlite3"
    make_paper_evidence(db, hours=2)
    result = run_check(db)
    assert result.returncode != 0
    assert "OVERNIGHT_CHECK_FAIL" in result.stdout
    assert "need 48.00h" in result.stdout

def test_overnight_check_does_not_reuse_old_historical_trades(tmp_path):
    db = tmp_path / "paper.sqlite3"
    make_paper_evidence(db, trade_age_hours=72)
    result = run_check(db)
    assert result.returncode != 0
    assert "only 0 fee-complete closed trades" in result.stdout


def test_overnight_counts_up_to_heartbeat_and_rejects_disconnects(tmp_path):
    db = tmp_path / "paper.sqlite3"
    make_paper_evidence(db, hours=49, heartbeat_minutes_ago=90, reconnects=1)
    result = run_check(db)
    assert result.returncode != 0
    assert "47.50h" in result.stdout
    assert "depth reconnects" in result.stdout
