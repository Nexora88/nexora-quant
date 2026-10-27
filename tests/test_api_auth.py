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
