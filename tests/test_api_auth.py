import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.api import app


def test_remote_api_requires_bearer_token(monkeypatch):
    monkeypatch.setenv("NEXORA_API_TOKEN", "test-secret-token")
    client = TestClient(app, client=("192.0.2.10", 12345))

    denied = client.get("/status")
    assert denied.status_code == 403

    allowed = client.get("/health", headers={"Authorization": "Bearer test-secret-token"})
    assert allowed.status_code != 403


def test_local_api_remains_available_without_token(monkeypatch):
    monkeypatch.delenv("NEXORA_API_TOKEN", raising=False)
    client = TestClient(app)
    assert client.get("/health").status_code == 200

def test_private_lan_requires_token_unless_explicitly_enabled(monkeypatch):
    monkeypatch.delenv("NEXORA_API_TOKEN", raising=False)
    monkeypatch.delenv("NEXORA_ALLOW_LAN", raising=False)
    client = TestClient(app, client=("192.168.1.25", 12345))
    assert client.get("/health").status_code == 403

    monkeypatch.setenv("NEXORA_API_TOKEN", "lan-test-token")
    assert client.get(
        "/health", headers={"Authorization": "Bearer lan-test-token"}
    ).status_code == 200

    monkeypatch.delenv("NEXORA_API_TOKEN", raising=False)
    monkeypatch.setenv("NEXORA_ALLOW_LAN", "true")
    assert client.get("/health").status_code == 200


def test_health_reports_engine_and_market_readiness():
    from app.api import health

    result = health()
    assert result["status"] in {"ok", "degraded", "error", "not_ready"}
    assert result["engine"] in {"not_started", "running", "failed", "stopped"}
    assert "market_data_connected" in result

def test_health_is_degraded_when_kill_switch_is_active(monkeypatch):
    import app.api as api

    monkeypatch.setattr(api, "_engine_task_status", lambda: "running")
    monkeypatch.setattr(api.state, "snapshot", lambda: {
        "connected": True,
        "kill_switch": True,
        "emergency": False,
        "data_age_seconds": 0.1,
        "last_error": None,
    })
    result = api.health()
    assert result["status"] == "degraded"
    assert result["kill_switch"] is True


def test_readiness_separates_liveness_from_trade_safety(monkeypatch):
    from dataclasses import replace
    from time import monotonic
    from types import SimpleNamespace

    import app.api as api
    import app.config as config
    from app.live_reconciliation import LocalAccountSnapshot

    monkeypatch.setattr(config, "settings", replace(config.settings, trading_mode="live"))
    monkeypatch.setattr(api, "_engine_task_status", lambda: "running")
    monkeypatch.setattr(api.state, "snapshot", lambda: {
        "connected": True,
        "kill_switch": False,
        "emergency": False,
    })
    executor = SimpleNamespace(
        order_state_uncertain=True, order_lists_reconciled=False,
        base_quantity=0.05, protective_order_list_id=None,
        symbol="BTCUSDT", trades=[], cash_usdt=50.0, fees_paid_usdt=0.0,
    )
    monkeypatch.setattr(api.state, "executor", executor)
    monkeypatch.setattr(api.state, "paused", False)
    monkeypatch.setattr(api.state, "exchange_reconciliation", {"status": "pass"})
    monkeypatch.setattr(api.state, "exchange_reconciled_at_monotonic", None)
    monkeypatch.setattr(api.state, "live_entry_cost_calibrated", False)

    client = TestClient(app)
    assert client.get("/health").status_code == 200
    blocked = client.get("/ready")
    assert blocked.status_code == 503
    assert set(blocked.json()["blockers"]) == {
        "exchange_reconciliation_unavailable_or_stale",
        "order_state_uncertain", "order_lists_unreconciled", "position_unprotected", "execution_cost_uncalibrated",
    }
    executor.order_state_uncertain = False
    executor.protective_order_list_id = 1
    monkeypatch.setattr(api.state, "exchange_reconciled_at_monotonic", monotonic())
    monkeypatch.setattr(api.state, "exchange_reconciled_revision", LocalAccountSnapshot.revision(executor))
    monkeypatch.setattr(api.state, "live_entry_cost_calibrated", True)
    assert client.get("/ready").json()["blockers"] == ["order_lists_unreconciled"]
    executor.order_lists_reconciled = True
    assert client.get("/ready").status_code == 200
    executor.cash_usdt -= 0.01
    assert client.get("/ready").json()["blockers"] == ["exchange_reconciliation_revision_changed"]
    monkeypatch.setattr(api.state, "exchange_reconciled_at_monotonic", monotonic() - 200)
    assert client.get("/ready").status_code == 503


def test_status_exposes_conservative_fee_schedule(monkeypatch):
    import app.api as api

    monkeypatch.setattr(api.state, "snapshot", lambda: {"connected": False})
    result = api.status()
    assert result["fee_schedule"]["taker_rate"] >= 0
    assert result["fee_schedule"]["maker_rate"] >= 0
    assert result["server_time"].endswith("+00:00")
    assert "BNB" in result["fee_schedule"]["assumption"]


def test_dashboard_uses_full_session_metrics_and_safe_dynamic_text():
    from app.api import dashboard

    html = dashboard()
    assert "const esc=" in html
    assert "s.session_expectancy" in html
    assert "s.max_drawdown_pct" in html
    assert "Veri birikiyor" in html
    assert "createLinearGradient" in html
    assert 'id="cash"' in html
    assert 'id="ltp"' in html
