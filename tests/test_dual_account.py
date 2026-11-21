from __future__ import annotations

import pytest

from app.dual_account import DualAccountStore


def setup_store(tmp_path):
    store = DualAccountStore(tmp_path / "accounts.sqlite3")
    store.register_account("paper-main", "paper", 20)
    store.register_account("live-main", "live", 20)
    return store


def valid_evidence():
    return {
        "closed_trades": 50,
        "oos_windows": 4,
        "positive_oos_windows": 3,
        "fee_net_expectancy_usdt": 0.02,
        "max_drawdown_pct": 4.5,
        "data_gaps": 0,
        "ledger_gaps": 0,
    }


def test_account_events_and_learner_state_are_isolated(tmp_path):
    store = setup_store(tmp_path)
    try:
        assert store.record_event("paper-main", "closed_trade", {"pnl_usdt": 1}, event_id="p1")
        assert not store.record_event("paper-main", "closed_trade", {"pnl_usdt": 1}, event_id="p1")
        store.save_learner_state("paper-main", {"trades": 7})
        store.save_learner_state("live-main", {"trades": 2})
        assert store.load_learner_state("paper-main") == {"trades": 7}
        assert store.load_learner_state("live-main") == {"trades": 2}
        with pytest.raises(ValueError):
            store.register_account("second-paper", "paper", 20)
    finally:
        store.close()


def test_strategy_candidate_requires_evidence_and_cannot_change_risk(tmp_path):
    store = setup_store(tmp_path)
    try:
        with pytest.raises(ValueError):
            store.publish_paper_candidate(
                "paper-main", {"max_daily_loss_usdt": 99}, valid_evidence(),
            )
        with pytest.raises(ValueError):
            store.publish_paper_candidate(
                "paper-main", {"entry_min_score": 0.3},
                {**valid_evidence(), "closed_trades": 10},
            )
        version = store.publish_paper_candidate(
            "paper-main",
            {"entry_min_score": 0.31, "size_bias": 0.95},
            valid_evidence(),
        )
        with pytest.raises(PermissionError):
            store.promote_candidate(version, "live-main")
        active = store.promote_candidate(
            version, "live-main", operator_approved=True,
        )
        assert active["version_id"] == version
        assert active["parameters"]["entry_min_score"] == 0.31
    finally:
        store.close()


def test_strategy_candidate_accepts_conservative_compound_fraction(tmp_path):
    store = setup_store(tmp_path)
    try:
        version = store.publish_paper_candidate(
            "paper-main", {"compound_fraction": 0.25}, valid_evidence(),
        )
        active = store.promote_candidate(version, "live-main", operator_approved=True)
        assert active["parameters"]["compound_fraction"] == 0.25
    finally:
        store.close()


def test_strategy_promotion_can_be_rolled_back(tmp_path):
    store = setup_store(tmp_path)
    try:
        first = store.publish_paper_candidate(
            "paper-main", {"entry_min_score": 0.30}, valid_evidence(),
        )
        second = store.publish_paper_candidate(
            "paper-main", {"entry_min_score": 0.32}, valid_evidence(),
        )
        store.promote_candidate(first, "live-main", operator_approved=True)
        store.promote_candidate(second, "live-main", operator_approved=True)
        assert store.rollback_strategy("live-main") == first
        assert store.active_strategy("live-main")["version_id"] == first
    finally:
        store.close()


def test_reconciliation_reports_drift_and_clean_snapshot(tmp_path):
    store = setup_store(tmp_path)
    try:
        clean = {
            "cash_usdt": 18.0, "base_quantity": 0.001,
            "fees_usdt": 0.02, "open_order_count": 1,
        }
        assert store.reconcile("live-main", clean, dict(clean))["status"] == "pass"
        drifted = {**clean, "cash_usdt": 17.5}
        result = store.reconcile("live-main", clean, drifted)
        assert result["status"] == "mismatch"
        assert "cash_usdt" in result["differences"]
    finally:
        store.close()


def test_live_learner_requires_exchange_confirmed_fee_complete_close(tmp_path):
    from app.intelligence.learner import OnlineLearner
    from app.dual_account import AccountLearningCoordinator

    store = setup_store(tmp_path)
    try:
        learner = OnlineLearner(frozen=False, min_trades_before_adapt=1)
        coordinator = AccountLearningCoordinator(
            store, "live-main", "live", learner,
        )
        with pytest.raises(ValueError):
            coordinator.record_closed_trade(
                0.1, event_id="live-1", accounting_complete=True,
                exchange_confirmed=False,
            )
        assert coordinator.record_closed_trade(
            0.1, event_id="live-1", accounting_complete=True,
            exchange_confirmed=True,
        )
        assert not coordinator.record_closed_trade(
            0.1, event_id="live-1", accounting_complete=True,
            exchange_confirmed=True,
        )
        restored = OnlineLearner(frozen=False, min_trades_before_adapt=1)
        restored_coordinator = AccountLearningCoordinator(
            store, "live-main", "live", restored,
        )
        assert restored_coordinator.restore()
        assert restored.to_dict()["lifetime_trades"] == 1
    finally:
        store.close()
