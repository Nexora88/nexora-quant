#!/usr/bin/env python3
"""48h overnight paper health check — expectancy must stay fee-positive.

Run while paper desk is live, or after a session:
  PYTHONPATH=. python scripts/overnight_paper_check.py

Exits non-zero if core expectancy math or config risk gates are broken.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from app.expectancy import asymmetric_expectancy
    from app.config import Settings
    from app.atr_stops import compute_dynamic_targets

    # 1) Fee-aware expectancy still positive at design R:R
    e = asymmetric_expectancy(
        win_rate=0.40, take_profit_pct=1.20, stop_loss_pct=0.35, fee_rate=0.001
    )
    if e <= 0:
        print(f"FAIL expectancy non-positive: {e}")
        return 1
    print(f"OK expectancy@40%wr TP1.2/SL0.35 fee0.1%: {e:.6f}")

    # 2) ATR targets keep R:R floor
    quiet = compute_dynamic_targets(atr_pct=0.001, regime="choppy")
    hot = compute_dynamic_targets(atr_pct=0.004, regime="trend")
    for name, t in (("quiet", quiet), ("hot", hot)):
        rr = t.take_profit_pct / t.stop_loss_pct if t.stop_loss_pct > 0 else 0
        if rr < 1.3:
            print(f"FAIL {name} R:R too tight: {rr}")
            return 1
        print(f"OK ATR {name}: SL={t.stop_loss_pct:.2f}% TP={t.take_profit_pct:.2f}% RR={rr:.2f}")

    # 3) Settings validate paper desk
    s = Settings(
        trading_mode="paper",
        starting_cash_usdt=100,
        order_size_usdt=15,
        max_order_size_usdt=25,
        entry_min_score=0.26,
        use_atr_targets=True,
        vol_target_enabled=True,
        risk_per_trade_pct=0.40,
        max_concurrent_positions=1,
    ).validate()
    if s.max_concurrent_positions != 1:
        print("FAIL multi-position should stay disabled for now")
        return 1
    print(f"OK settings cash={s.starting_cash_usdt} concurrent={s.max_concurrent_positions} atr={s.use_atr_targets}")

    # 4) Optional: read paper sqlite trade count if present
    db = ROOT / "data" / "paper.sqlite3"
    if db.exists():
        import sqlite3
        con = sqlite3.connect(str(db))
        try:
            n = con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        except Exception:
            n = -1
        finally:
            con.close()
        print(f"INFO paper trades logged: {n}")
    else:
        print("INFO no paper.sqlite3 yet — start uvicorn for overnight run")

    print("OVERNIGHT_CHECK_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
