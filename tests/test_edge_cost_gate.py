from app.decision import FeatureVote
from app.intelligence.edge import score_edge


def test_round_trip_fees_and_impact_can_block_trade():
    votes = [FeatureVote("obi", "long", 1.0, 0.8, "positive imbalance")]
    report = score_edge(
        votes=votes, spread_bps=2, impact_bps=2, fee_bps=20,
        latency_bps=1, expected_alpha_bps=15,
    )
    assert report.cost_bps == 25
    assert report.net_edge_bps == -10
    assert not report.tradeable


def test_positive_net_edge_is_required_even_with_high_quality():
    votes = [FeatureVote("obi", "long", 1.0, 0.8, "positive imbalance")]
    report = score_edge(
        votes=votes, spread_bps=1, impact_bps=1, fee_bps=2,
        expected_alpha_bps=15, min_net_edge_bps=2,
    )
    assert report.net_edge_bps == 11
    assert report.tradeable


def test_no_votes_never_trade():
    report = score_edge(votes=[], spread_bps=1, impact_bps=1, fee_bps=2)
    assert not report.tradeable
    assert report.net_edge_bps == -4
    assert "no_votes" in report.notes


def test_negative_cost_is_clamped_not_raised():
    # Bad ticks must not crash the L2 loop; costs are clamped to >= 0.
    report = score_edge(votes=[], spread_bps=-1, impact_bps=-2)
    assert report.cost_bps >= 0
    assert "clamped_negative_cost_inputs" in report.notes
    assert not report.tradeable


def test_paper_soft_min_net_edge_allowed():
    votes = [FeatureVote("obi", "long", 1.0, 0.9, "strong")]
    report = score_edge(
        votes=votes, spread_bps=1, impact_bps=1, fee_bps=2,
        expected_alpha_bps=15, min_quality=0.2, min_net_edge_bps=-4.0,
    )
    assert report.tradeable  # net ~11.5 >= -4
