"""Opt-in lifecycle through the production executor, using only simulated funds."""
import os

import pytest

from app.binance_rest import BinanceRestClient
from app.live import LiveExecutor
from app.storage import PaperStore

pytestmark = pytest.mark.skipif(
    os.getenv("NEXORA_RUN_SPOT_TESTNET_E2E") != "1",
    reason="requires explicit opt-in and a dedicated simulated-fund Spot Testnet account",
)

SYMBOL = "BTCUSDT"
QUOTE_USDT = 20.0
STATE_KEY = f"live:{SYMBOL}"


def test_spot_testnet_market_oco_restart_cancel_and_exit(tmp_path):
    assert os.getenv("BINANCE_TESTNET") == "true" and os.getenv("TRADING_MODE") == "paper"
    key = os.getenv("BINANCE_API_KEY")
    secret = os.getenv("BINANCE_API_SECRET")
    if not key or not secret:
        pytest.fail("Configure the two dedicated Spot Testnet GitHub Actions secrets")
    client = BinanceRestClient(api_key=key, api_secret=secret, testnet=True)
    assert client.testnet and client.base == "https://testnet.binance.vision"
    client.ping()
    db = str(tmp_path / "spot-testnet.sqlite")

    def executor(store, *, restore=False):
        ex = LiveExecutor(client, symbol=SYMBOL, fee_rate=0.001, base_asset="BTC", quote_asset="USDT")
        if restore:
            ex.restore(store.load_state(STATE_KEY)["account"])
        ex.attach_order_journal(store, STATE_KEY)
        return ex

    with PaperStore(db, async_writes=False) as store:
        ex = executor(store)
        step = float(ex._load_filters()["LOT_SIZE"]["stepSize"])
        base_before = client.free_balance("BTC")
        assert 0 <= base_before < step, "Use an isolated Testnet account with no tradable BTC"
        assert not client.open_orders(SYMBOL)
        assert not client.open_order_lists()
        ex.cash_usdt = ex.starting_cash_usdt = client.free_balance("USDT")
        assert ex.cash_usdt > QUOTE_USDT and ex._min_notional() < QUOTE_USDT
        buy = ex.buy(notional_usdt=QUOTE_USDT, price=client.ticker_price(SYMBOL), reason="testnet_e2e")
        try:
            assert buy and buy["accounting_complete"] and buy["quantity"] > 0
            assert store.pending_live_order() is None
            assert ex.ensure_protective_oco(
                current_price=client.ticker_price(SYMBOL), take_profit_pct=5, stop_loss_pct=5,
            )
            list_id = ex.protective_order_list_id
            assert list_id is not None
            assert store.load_state(STATE_KEY)["account"]["protective_order_list_id"] == list_id
        except Exception:
            # May flatten only when a competing protective sell has been ruled out.
            ex.emergency_flatten(reason="testnet_protection_assertion")
            raise

    with PaperStore(db, async_writes=False) as store:
        ex = executor(store, restore=True)
        try:
            assert ex.reconcile_uncertain_order()
            assert ex.protective_order_list_id == list_id
            assert ex.cancel_protective_oco(), "No competing sell without confirmed terminal OCO children"
        finally:
            if not ex.order_state_uncertain and ex.protective_order_list_id is None and ex.base_quantity >= step:
                sold = ex.sell_all(price=client.ticker_price(SYMBOL), reason="testnet_e2e_exit")
                assert sold and sold["accounting_complete"], "Exit fill and actual commission required"
        assert store.pending_live_order() is None
        assert not client.open_orders(SYMBOL)
        assert not client.open_order_lists()
        assert ex.base_quantity < step
        assert client.free_balance("BTC") - base_before < step
        assert len(ex.trades) >= 2
        assert store.load_state(STATE_KEY)["account"]["trades"] == ex.trades
