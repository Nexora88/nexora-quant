from dataclasses import dataclass

from app.state import RuntimeState


@dataclass(slots=True)
class Snapshot:
    trades: int
    note: str


def test_runtime_snapshot_serializes_dataclass_learner_snapshot():
    state = RuntimeState()
    state.learner_snapshot = Snapshot(trades=7, note="restored")
    result = state.snapshot()
    assert result["learner_snapshot"] == {"trades": 7, "note": "restored"}


def test_runtime_snapshot_keeps_mapping_learner_snapshot():
    state = RuntimeState()
    state.learner_snapshot = {"trades": 3, "note": "ok"}
    result = state.snapshot()
    assert result["learner_snapshot"] == {"trades": 3, "note": "ok"}
