from app.decision import FeatureVote
from app.intelligence.edge import score_edge


def _votes():
    return [FeatureVote("confluence", "long", 1.0, 1.0, "aligned")]


def test_gross_move_must_cover_two_times_all_in_costs():
    blocked = score_edge(
        votes=_votes(), spread_bps=2, impact_bps=2, fee_bps=4,
        latency_bps=2, expected_alpha_bps=19, min_quality=0.4,
        min_net_edge_bps=0.1, min_cost_multiple=2.0,
    )
    allowed = score_edge(
        votes=_votes(), spread_bps=2, impact_bps=2, fee_bps=4,
        latency_bps=2, expected_alpha_bps=20, min_quality=0.4,
        min_net_edge_bps=0.1, min_cost_multiple=2.0,
    )
    assert blocked.cost_bps == 10
    assert blocked.net_edge_bps == 9
    assert not blocked.tradeable
    assert allowed.net_edge_bps == 10
    assert allowed.tradeable


def test_paper_soft_gates_cannot_override_two_times_cost_floor():
    report = score_edge(
        votes=_votes(), spread_bps=2, impact_bps=2, fee_bps=4,
        latency_bps=2, expected_alpha_bps=19, min_quality=0.9,
        min_net_edge_bps=5, min_cost_multiple=2.0, paper_soft_gates=True,
    )
    assert "paper_soft_gates" in report.notes
    assert not report.tradeable



def test_desk_wrapper_uses_configured_cost_multiple():
    from app.intelligence.edge import score_edge_for_desk

    votes = _votes()
    blocked = score_edge_for_desk(
        votes=votes, spread_bps=1, impact_bps=20, fee_bps=20,
        latency_bps=0, take_profit_pct=1.0, mode="paper",
        paper_soft_gates=False, min_cost_multiple=2.0,
    )
    allowed = score_edge_for_desk(
        votes=votes, spread_bps=1, impact_bps=19, fee_bps=20,
        latency_bps=0, take_profit_pct=1.0, mode="paper",
        paper_soft_gates=False, min_cost_multiple=2.0,
    )
    assert not blocked.tradeable
    assert allowed.tradeable
