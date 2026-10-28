"""Universe screen helpers (offline-safe)."""
from __future__ import annotations

from app.universe import (
    DEFAULT_UNIVERSE,
    UniverseRow,
    default_universe,
    depth_watch_from_screen,
    screen_universe,
)


def test_default_universe_size():
    u = default_universe()
    assert 25 <= len(u) <= 40
    assert "btcusdt" in u
    assert "ethusdt" in u


def test_depth_watch_includes_btc():
    rows = [
        UniverseRow("solusdt", 1e9, 100.0, 2.0, 100.0),
        UniverseRow("ethusdt", 2e9, 2000.0, 1.0, 90.0),
    ]
    w = depth_watch_from_screen(rows, max_depth=3)
    assert "btcusdt" in w
    assert w[0] in ("solusdt", "ethusdt", "btcusdt")


def test_screen_fallback_without_network(monkeypatch):
    def boom(*a, **k):
        raise OSError("no net")

    monkeypatch.setattr("app.universe.fetch_24h_tickers", boom)
    rows = screen_universe(candidates=["btcusdt", "ethusdt", "solusdt"], top_n=2)
    assert len(rows) >= 1
    assert rows[0].symbol in DEFAULT_UNIVERSE or rows[0].symbol == "btcusdt"
