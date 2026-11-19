"""Import smoke tests for the supported runtime entry points."""

def test_runtime_import_smoke():
    from app.state import RuntimeState
    from app.live import LiveExecutor

    assert RuntimeState is not None
    assert LiveExecutor is not None


def test_fastapi_application_import_smoke():
    from app.api import app

    assert app is not None
    assert any(getattr(route, "path", None) == "/health" for route in app.routes)
    assert any(getattr(route, "path", None) == "/status" for route in app.routes)

def test_dashboard_and_status_endpoints_smoke():
    from fastapi.testclient import TestClient
    from app.api import app

    with TestClient(app) as client:
        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert 'id="sessionpnl"' in dashboard.text
        assert 'id="exitreasons"' in dashboard.text
        assert 'id="makerfill"' in dashboard.text
        assert 'id="markout1"' in dashboard.text
        assert 'id="markout5"' in dashboard.text
        assert 'id="markout30"' in dashboard.text
        assert client.get("/health").status_code == 200
        status = client.get("/status")
        assert status.status_code == 200
        payload = status.json()
        assert "session_expectancy" in payload
        assert "maker_stats" in payload
