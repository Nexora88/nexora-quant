"""Multi-symbol watch list and fan-in helpers."""
from __future__ import annotations

from app.multi_stream import watch_list


def test_watch_list_dedupes_and_adds_btc_for_alts():
    w = watch_list("solusdt", ("ethusdt", "solusdt", "bnbusdt"))
    assert w[0] == "solusdt"
    assert "ethusdt" in w
    assert "bnbusdt" in w
    assert "btcusdt" in w


def test_watch_list_btc_only_no_dup():
    w = watch_list("btcusdt", ())
    assert w == ["btcusdt"]
