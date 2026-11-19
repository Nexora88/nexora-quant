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
