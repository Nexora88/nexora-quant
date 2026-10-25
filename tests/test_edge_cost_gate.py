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


def test_negative_cost_is_rejected():
    try:
        score_edge(votes=[], spread_bps=-1)
    except ValueError as exc:
        assert "cannot be negative" in str(exc)
    else:
        raise AssertionError("negative cost should be rejected")
