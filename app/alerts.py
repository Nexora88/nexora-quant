"""Outbound ops alerts (Telegram / Discord webhooks).

Fire-and-forget HTTP posts. Failures are logged only — never block the engine.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)


def _post_json(url: str, payload: dict[str, Any], timeout: float = 5.0) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "nexora-quant/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()


def notify(event: str, message: str, *, extra: dict[str, Any] | None = None) -> None:
    """Send alert to configured Discord and/or Telegram endpoints."""
    body = f"[Nexora Quant] {event}: {message}"
    if extra:
        body += " | " + ", ".join(f"{k}={v}" for k, v in list(extra.items())[:8])

    discord = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if discord:
        try:
            _post_json(discord, {"content": body[:1900]})
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            log.warning("Discord alert failed: %s", exc)

    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if tg_token and tg_chat:
        try:
            url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            _post_json(url, {"chat_id": tg_chat, "text": body[:3500]})
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            log.warning("Telegram alert failed: %s", exc)


def alert_kill_switch(reason: str) -> None:
    notify("KILL_SWITCH", reason)


def alert_emergency_flatten(reason: str) -> None:
    notify("EMERGENCY_FLATTEN", reason)
