import pytest

from app.order_state import OrderState, OrderStateMachine


def test_order_lifecycle_pending_open_partial_filled():
    machine = OrderStateMachine()
    machine.begin("nq-intent-1")
    assert machine.state is OrderState.PENDING
    assert machine.observe("NEW") is OrderState.OPEN
    assert machine.observe("PARTIALLY_FILLED") is OrderState.PARTIALLY_FILLED
    assert machine.observe("FILLED") is OrderState.FILLED
    assert machine.terminal


def test_unknown_order_blocks_second_intent_until_reconciled_terminal():
    machine = OrderStateMachine()
    machine.begin("nq-intent-1")
    machine.mark_unknown()
    with pytest.raises(RuntimeError, match="Previous order intent"):
        machine.begin("nq-intent-2")
    assert machine.observe("FILLED") is OrderState.FILLED
    machine.begin("nq-intent-2")


def test_lost_response_can_be_resolved_without_resubmitting():
    machine = OrderStateMachine()
    machine.begin("nq-intent-1")
    machine.mark_unknown()
    assert machine.observe("CANCELED") is OrderState.CANCELLED
    assert machine.client_order_id == "nq-intent-1"


def test_terminal_state_cannot_be_reversed_to_open():
    machine = OrderStateMachine()
    machine.begin("nq-intent-1")
    machine.observe("FILLED")
    with pytest.raises(RuntimeError, match="Invalid order state transition"):
        machine.observe("NEW")


def test_unknown_exchange_status_fails_closed():
    machine = OrderStateMachine()
    machine.begin("nq-intent-1")
    assert machine.observe("SOMETHING_NEW") is OrderState.UNKNOWN
    assert machine.blocks_new_orders


def test_state_machine_snapshot_restores_unknown_order():
    machine = OrderStateMachine()
    machine.begin("nq-intent-1")
    machine.mark_unknown()
    restored = OrderStateMachine()
    restored.restore(machine.snapshot())
    assert restored.state is OrderState.UNKNOWN
    assert restored.client_order_id == "nq-intent-1"
    with pytest.raises(RuntimeError):
        restored.begin("nq-intent-2")
