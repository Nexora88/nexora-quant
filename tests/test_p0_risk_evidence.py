from datetime import datetime, timezone, timedelta

from app.events import BookTicker
from app.risk import RiskManager
from app.state import RuntimeState


def make_risk(max_daily_fee_usdt=0.75):
    return RiskManager(
        max_order_size_usdt=50,
        max_daily_loss_usdt=25,
        max_consecutive_losses=3,
        max_spread_bps=20,
        max_data_age_seconds=5,
        max_daily_fee_usdt=max_daily_fee_usdt,
    )


def test_daily_fee_budget_is_a_hard_entry_gate_and_rolls_at_utc_day():
    risk = make_risk(0.10)
    risk.record_fee(0.10)
    decision = risk.evaluate_entry(
        notional_usdt=10, available_cash=100, bid=99.99, ask=100.00,
        data_age_seconds=0.1,
    )
    assert not decision.allowed
    assert decision.reason == "Daily fee budget reached"

    risk.rollover_day("2026-11-20")
    assert risk.fees_paid_today == 0
    assert risk.evaluate_entry(
        notional_usdt=10, available_cash=100, bid=99.99, ask=100.00,
        data_age_seconds=0.1,
    ).allowed


def test_daily_fee_counter_roundtrips_in_risk_snapshot():
    first = make_risk()
    first.record_fee(0.23)
    restored = make_risk()
    restored.restore(first.snapshot())
    assert restored.fees_paid_today == 0.23


def test_session_evidence_roundtrips_without_losing_closed_trade_history():
    state = RuntimeState()
    state.session_fees_usdt = 0.42
    state.session_fee_day = "2026-11-19"
    state.session_closed_trade_pnls = [0.12, -0.03]
    state.closed_trade_count = 2
    state.session_realized_pnl_usdt = 0.09
    state.max_drawdown_pct_observed = 1.25
    state.session_exit_reasons = {"take_profit": 1, "stop_loss": 1}
    state.maker_entry_attempts = 4
    state.maker_entry_fills = 2
    state.maker_entry_timeouts = 1

    restored = RuntimeState()
    restored.restore_evidence(state.evidence_snapshot())
    assert restored.session_expectancy()["n"] == 2
    assert restored.session_expectancy()["sum_pnl_usdt"] == 0.09
    assert restored.session_fees_usdt == 0.42
    assert restored.closed_trade_count == 2
    assert restored.max_drawdown_pct_observed == 1.25
    assert restored.maker_stats()["attempts"] == 4


def test_fill_markouts_are_recorded_at_one_five_and_thirty_seconds():
    state = RuntimeState()
    fill_ts = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)
    state.record_fill({
        "side": "buy", "price": 100.0, "fee_usdt": 0.01,
        "timestamp": fill_ts.isoformat(), "symbol": "btcusdt",
    })

    for seconds, mid in ((1, 100.1), (5, 100.2), (30, 99.9)):
        state.update_book(BookTicker(
            symbol="btcusdt", bid=mid - 0.01, bid_qty=1,
            ask=mid + 0.01, ask_qty=1,
            received_at=fill_ts.replace(microsecond=0) + timedelta(seconds=seconds),
        ))

    rows = list(state.markout_history)
    assert [row["horizon_seconds"] for row in rows] == [1, 5, 30]
    assert rows[0]["markout_bps"] > 0
    assert rows[2]["markout_bps"] < 0

def test_paper_executor_emits_actual_fills_to_evidence_callback():
    from app.paper import PaperExecutor

    state = RuntimeState()
    state.risk_manager = make_risk()
    paper = PaperExecutor(100, 0.001)
    paper.on_fill = state.record_fill
    paper.buy(notional_usdt=10, price=100, reason="entry")
    paper.sell_all(price=101, reason="exit")

    assert state.maker_stats()["attempts"] == 0
    assert state.session_fees_usdt > 0
    assert state.risk_manager.fees_paid_today == state.session_fees_usdt
    assert state.closed_trade_count == 1
    assert state.session_expectancy()["n"] == 1
