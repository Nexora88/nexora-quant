"""Lightweight HMAC token auth for remote dashboard access.

Supports:
  - static bearer NEXORA_API_TOKEN (simple ops token)
  - signed JWT-like tokens (header.payload.sig) when NEXORA_JWT_SECRET is set

Not a full OAuth2 provider; adequate for single-operator VPS monitoring.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def issue_token(*, subject: str = "operator", ttl_seconds: int | None = None) -> str:
    secret = os.getenv("NEXORA_JWT_SECRET", "")
    if not secret:
        raise ValueError("NEXORA_JWT_SECRET is required to issue tokens")
    ttl = ttl_seconds if ttl_seconds is not None else int(os.getenv("NEXORA_JWT_TTL_SECONDS", "86400"))
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload_obj = {"sub": subject, "iat": int(time.time()), "exp": int(time.time()) + max(60, ttl)}
    payload = _b64url(json.dumps(payload_obj, separators=(",", ":")).encode())
    msg = f"{header}.{payload}".encode()
    sig = _b64url(hmac.new(secret.encode(), msg, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def verify_bearer(authorization: str | None) -> bool:
    if not authorization or not authorization.startswith("Bearer "):
        return False
    token = authorization[7:].strip()
    static = os.getenv("NEXORA_API_TOKEN", "")
    if static and hmac.compare_digest(token, static):
        return True
    secret = os.getenv("NEXORA_JWT_SECRET", "")
    if not secret or token.count(".") != 2:
        return False
    header_b64, payload_b64, sig_b64 = token.split(".", 2)
    msg = f"{header_b64}.{payload_b64}".encode()
    expected = _b64url(hmac.new(secret.encode(), msg, hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig_b64):
        return False
    try:
        payload: dict[str, Any] = json.loads(_b64url_decode(payload_b64))
    except Exception:
        return False
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        return False
    return True
