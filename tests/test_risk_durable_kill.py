"""Kill switch must survive process restart via durable file."""
from __future__ import annotations

from app.risk import RiskManager


def _rm() -> RiskManager:
    return RiskManager(
        max_order_size_usdt=50,
        max_daily_loss_usdt=5,
        max_consecutive_losses=3,
        max_spread_bps=20,
        max_data_age_seconds=5,
    )


def test_kill_switch_persists_across_instances(tmp_path, monkeypatch) -> None:
    kill = tmp_path / "risk_kill_switch.json"
    monkeypatch.setattr("app.risk._KILL_FILE", kill)
    monkeypatch.setenv("NEXORA_DURABLE_KILL", "1")
    a = _rm()
    a.activate_kill_switch("Daily loss limit reached")
    assert kill.is_file()
    b = _rm()
    assert b.kill_switch is True
    assert "Daily loss" in (b.kill_switch_reason or "")
    b.clear_kill_switch()
    assert not kill.is_file()
    c = _rm()
    assert c.kill_switch is False


def test_snapshot_restore_roundtrip(monkeypatch) -> None:
    monkeypatch.setenv("NEXORA_DURABLE_KILL", "1")
    a = _rm()
    a.realized_pnl_today = -3.5
    a.consecutive_losses = 2
    a.activate_kill_switch("Consecutive-loss limit reached")
    snap = a.snapshot()
    b = _rm()
    b.restore(snap)
    assert b.kill_switch is True
    assert b.consecutive_losses == 2
    assert abs(b.realized_pnl_today + 3.5) < 1e-9
    a.clear_kill_switch()
