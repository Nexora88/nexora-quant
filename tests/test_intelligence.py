from app.decision import FeatureVote
from app.intelligence.adverse import AdverseSelectionFilter
from app.intelligence.edge import score_edge


def test_edge_requires_agreement_and_cost():
    votes = [
        FeatureVote("a", "long", 0.4, 1.0, "x"),
        FeatureVote("b", "long", 0.3, 1.0, "y"),
        FeatureVote("c", "short", 0.1, -1.0, "z"),
    ]
    good = score_edge(votes=votes, spread_bps=2.0, impact_bps=1.0, min_quality=0.4, min_net_edge_bps=1.0)
    assert good.agreement > 0.5
    bad = score_edge(votes=votes, spread_bps=40.0, impact_bps=10.0)
    assert bad.tradeable is False


def test_adverse_flags_spread_spike():
    f = AdverseSelectionFilter()
    for _ in range(15):
        f.update(mid=100.0, spread_bps=2.0, micro_price=100.0)
    f.update(mid=100.0, spread_bps=25.0, micro_price=100.0)
    v = f.check(intend_long=True)
    assert v.toxic
    assert any("spread" in r for r in v.reasons)
