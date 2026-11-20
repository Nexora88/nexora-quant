#!/usr/bin/env python3
"""Publish, promote or roll back account-isolated strategy versions.

Publishing requires measured evidence JSON. Promotion is a separate explicit
operator action. This tool never changes account balances or submits orders.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.dual_account import DualAccountStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("publish", "promote", "rollback", "active"),
    )
    parser.add_argument("--db", type=Path, default=Path(
        os.getenv("DUAL_ACCOUNT_DB_PATH", "data/dual-account.sqlite3")
    ))
    parser.add_argument("--paper-account", default="paper-main")
    parser.add_argument("--live-account", default="live-main")
    parser.add_argument("--version")
    parser.add_argument("--evidence-json", type=Path)
    parser.add_argument("--i-approve-live-strategy", action="store_true")
    args = parser.parse_args()

    store = DualAccountStore(args.db)
    try:
        if args.action == "publish":
            if not args.evidence_json or not args.evidence_json.is_file():
                parser.error("publish requires --evidence-json with measured OOS evidence")
            learner = store.load_learner_state(args.paper_account)
            if not learner:
                raise RuntimeError("paper learner state is missing")
            parameters = {
                "entry_min_score": learner["entry_min"],
                "size_bias": learner["size_bias"],
                "tp_scale": learner["tp_scale"],
                "compound_fraction": learner["compound"],
            }
            evidence = json.loads(args.evidence_json.read_text(encoding="utf-8"))
            version = store.publish_paper_candidate(
                args.paper_account, parameters, evidence,
            )
            print(f"STRATEGY_CANDIDATE_PUBLISHED version={version}")
        elif args.action == "promote":
            if not args.version:
                parser.error("promote requires --version")
            if not args.i_approve_live_strategy:
                parser.error("promote requires --i-approve-live-strategy")
            result = store.promote_candidate(
                args.version, args.live_account, operator_approved=True,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
        elif args.action == "rollback":
            version = store.rollback_strategy(args.live_account)
            print(f"STRATEGY_ROLLBACK version={version}")
        else:
            result = store.active_strategy(args.live_account)
            print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
