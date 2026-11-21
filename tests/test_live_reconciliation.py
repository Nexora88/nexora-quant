import pytest

from app.live_reconciliation import audit_exchange_history, load_local_trade_ledger


def audit(**overrides):
    values = {
        "symbol": "BTCUSDT",
        "quote_asset": "USDT",
        "base_asset": "BTC",
        "local_cash": 90.0,
        "exchange_cash": 90.0,
        "local_base": 0.1,
        "exchange_base": 0.1,
        "local_fees_usdt": 0.12,
        "expected_oco_list_id": 8,
        "local_trade_rows": [{"trade": {"exchange_order_id": 11, "fee_usdt": 0.12,
            "commission_by_asset": {"USDT": 0.12},
            "commission_usdt_by_asset": {"USDT": 0.12}}}],
        "executor_trades": [],
        "exchange_orders": [{"symbol": "BTCUSDT", "orderId": 11, "status": "FILLED"}],
        "exchange_trades": [{
            "symbol": "BTCUSDT", "id": 1, "orderId": 11, "price": "100",
            "qty": "0.1", "commission": "0.12", "commissionAsset": "USDT",
        }],
        "open_orders": [{"symbol": "BTCUSDT", "orderId": 22, "status": "NEW"}],
        "open_order_lists": [{
            "symbol": "BTCUSDT", "orderListId": 8, "listStatusType": "EXECUTING",
            "orderReports": [{"orderId": 22}, {"orderId": 23}],
        }],
        "ticker_price": lambda symbol: 300.0,
    }
    values.update(overrides)
    return audit_exchange_history(**values)


def test_complete_history_commissions_and_oco_children_reconcile():
    result = audit()
    assert result["local"] == result["exchange"]
    assert result["exchange"]["fees_usdt"] == pytest.approx(0.12)
    assert result["details"]["exchange_fill_count"] == 1
    assert result["details"]["missing_local_order_ids"] == []
    assert result["exchange"]["unknown_open_order_count"] == 0


def test_exchange_fill_missing_from_local_ledger_is_a_hard_mismatch():
    result = audit(local_trade_rows=[])
    assert result["exchange"]["unmatched_exchange_order_count"] == 1
    assert result["details"]["missing_local_order_ids"] == [11]


def test_local_order_missing_from_exchange_history_is_a_hard_mismatch():
    result = audit(
        exchange_orders=[],
        exchange_trades=[],
        local_fees_usdt=0.0,
        local_base=0.0,
    )
    assert result["exchange"]["unmatched_local_order_count"] == 1
    assert result["details"]["missing_exchange_order_ids"] == [11]


def test_base_asset_commission_is_valued_at_fill_price():
    result = audit(
        local_fees_usdt=0.01,
        local_trade_rows=[{"trade": {"exchange_order_id": 11, "fee_usdt": 0.01,
         "commission_by_asset": {"BTC": 0.0001},
         "commission_usdt_by_asset": {"BTC": 0.01}}}],
        exchange_trades=[{
            "symbol": "BTCUSDT", "id": 2, "orderId": 11, "price": "100",
            "qty": "0.1", "commission": "0.0001", "commissionAsset": "BTC",
        }],
    )
    assert result["exchange"]["fees_usdt"] == pytest.approx(0.01)


def test_third_asset_commission_uses_exchange_conversion_price():
    result = audit(
        local_fees_usdt=0.03,
        local_trade_rows=[{"trade": {"exchange_order_id": 11, "fee_usdt": 0.03,
         "commission_by_asset": {"BNB": 0.0001},
         "commission_usdt_by_asset": {"BNB": 0.03}}}],
        exchange_trades=[{
            "symbol": "BTCUSDT", "id": 3, "orderId": 11, "price": "100",
            "qty": "0.1", "commission": "0.0001", "commissionAsset": "BNB",
        }],
    )
    assert result["exchange"]["fees_usdt"] == pytest.approx(0.03)


def test_unpriced_commission_is_reported_not_silently_dropped():
    result = audit(
        exchange_trades=[{
            "symbol": "BTCUSDT", "id": 4, "orderId": 11, "price": "100",
            "qty": "0.1", "commission": "0.0001", "commissionAsset": "XYZ",
        }],
        ticker_price=lambda symbol: (_ for _ in ()).throw(RuntimeError("pair unavailable")),
    )
    assert result["exchange"]["unpriced_commission_count"] == 1


def test_unmanaged_normal_open_order_is_detected_even_with_an_active_oco():
    result = audit(
        open_orders=[
            {"symbol": "BTCUSDT", "orderId": 22, "status": "NEW"},
            {"symbol": "BTCUSDT", "orderId": 99, "status": "NEW"},
        ],
    )
    assert result["exchange"]["unknown_open_order_count"] == 1
    assert result["details"]["unknown_open_order_ids"] == [99]


def test_unexpected_active_oco_list_is_detected():
    result = audit(
        open_orders=[],
        open_order_lists=[{
            "symbol": "BTCUSDT", "orderListId": 88, "listStatusType": "EXECUTING",
            "orderReports": [],
        }],
    )
    assert result["exchange"]["unknown_open_order_count"] == 1
    assert result["details"]["unexpected_active_order_list_ids"] == [88]


def test_local_trade_ledger_reads_every_page():
    class Store:
        def __init__(self):
            self.calls = []

        def list_trades(self, *, limit, before_id=None):
            self.calls.append((limit, before_id))
            if before_id is None:
                return [{"id": value} for value in range(1000, 0, -1)]
            if before_id == 1:
                return [{"id": 0}]
            return []

    store = Store()
    rows = load_local_trade_ledger(store)
    assert len(rows) == 1001
    assert rows[0]["id"] == 1000 and rows[-1]["id"] == 0
    assert store.calls == [(1000, None), (1000, 1)]


def test_local_trade_ledger_rejects_non_advancing_pagination():
    class Store:
        def list_trades(self, *, limit, before_id=None):
            return [{"id": value} for value in range(1000, 0, -1)]

    with pytest.raises(RuntimeError, match="did not advance"):
        load_local_trade_ledger(Store())



def test_native_commission_asset_delta_is_detected_even_when_order_ids_match():
    result = audit(local_trade_rows=[{"trade": {
        "exchange_order_id": 11,
        "commission_by_asset": {"USDT": 0.11},
        "commission_usdt_by_asset": {"USDT": 0.11},
        "accounting_complete": True,
    }}], local_fees_usdt=0.11)
    assert result["exchange"]["fee_asset_mismatch_count"] == 1
