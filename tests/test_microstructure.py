from app.analytics.microstructure import (
    OrnsteinUhlenbeckTracker,
    calculate_micro_price,
    calculate_weighted_obi,
)
from app.analytics.regime import MarketRegime, RegimeClassifier
from app.dynamic_gate import DynamicKellyGate
from app.strategy import PriceWindow, analyze_market


def test_weighted_obi_bid_pressure():
    bids = [(100, 10), (99.9, 8), (99.8, 5)]
    asks = [(100.1, 2), (100.2, 2), (100.3, 1)]
    obi = calculate_weighted_obi(bids, asks, levels=3)
    assert obi is not None and obi > 0.3


def test_micro_price_between_bid_ask():
    mp = calculate_micro_price(bid=100, ask=100.2, bid_qty=5, ask_qty=1)
    assert mp is not None
    assert 100 < mp < 100.2


def test_ou_zscore_extreme():
    ou = OrnsteinUhlenbeckTracker(maxlen=50, z_entry=2.0)
    for _ in range(40):
        ou.update(0.0)
    for _ in range(10):
        ou.update(0.9)
    z = ou.zscore()
    assert z is not None and z > 1.5


def test_kelly_positive_edge_sizes():
    k = DynamicKellyGate(max_order_usdt=50, min_order_usdt=5)
    for _ in range(10):
        k.record_pnl(2.0)
    for _ in range(5):
        k.record_pnl(-1.0)
    d = k.size(free_usdt=1000)
    assert d.notional_usdt >= 5


def test_regime_and_composite_signal():
    window = PriceWindow()
    ou = OrnsteinUhlenbeckTracker(maxlen=50)
    regime = RegimeClassifier()
    for i in range(40):
        mid = 100 + i * 0.01
        window.push(mid)
        regime.update(mid=mid, spread_bps=2.0, volume_proxy=10)
        ou.update(0.1)
    analysis = analyze_market(
        bid=100.5,
        ask=100.55,
        bid_qty=20,
        ask_qty=2,
        price_window=window,
        imbalance_threshold=0.65,
        bids=[(100.5, 20), (100.4, 15)],
        asks=[(100.55, 2), (100.6, 2)],
        ou=ou,
        regime_classifier=regime,
    )
    assert analysis.weighted_obi is not None
    assert analysis.micro_price is not None
    assert analysis.regime in {r.value for r in MarketRegime}
