import os

from app.auth import issue_token, verify_bearer


def test_static_and_jwt_tokens(monkeypatch):
    monkeypatch.setenv("NEXORA_API_TOKEN", "static-secret")
    monkeypatch.setenv("NEXORA_JWT_SECRET", "jwt-secret-key")
    assert verify_bearer("Bearer static-secret")
    assert not verify_bearer("Bearer wrong")
    token = issue_token(subject="test", ttl_seconds=60)
    assert verify_bearer(f"Bearer {token}")
    assert not verify_bearer("Bearer a.b.c")
