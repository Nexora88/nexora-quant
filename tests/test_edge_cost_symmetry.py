"""Paper and live must both charge round-trip impact in the edge gate."""
from __future__ import annotations

from app.decision import FeatureVote
from app.intelligence.edge import score_edge_for_desk


def _long_votes() -> list[FeatureVote]:
    return [
        FeatureVote(name="weighted_obi", direction="long", weight=0.4, value=0.7, note="t"),
        FeatureVote(name="momentum", direction="long", weight=0.3, value=2.0, note="t"),
    ]


def test_paper_and_live_same_rt_impact_fee_path() -> None:
    """With identical cost inputs, net edge is mode-symmetric (latency included)."""
    votes = _long_votes()
    spread = 1.5
    rt_impact = 4.0  # 2x one-way
    rt_fee = 15.0
    latency = 1.0
    paper = score_edge_for_desk(
        votes=votes,
        spread_bps=spread,
        impact_bps=rt_impact,
        fee_bps=rt_fee,
        latency_bps=latency,
        take_profit_pct=0.55,
        atr_pct=0.3,
        regime="trend",
        mode="paper",
        entry_min_score=0.20,
        paper_soft_gates=False,
    )
    live = score_edge_for_desk(
        votes=votes,
        spread_bps=spread,
        impact_bps=rt_impact,
        fee_bps=rt_fee,
        latency_bps=latency,
        take_profit_pct=0.55,
        atr_pct=0.3,
        regime="trend",
        mode="live",
        entry_min_score=0.20,
        paper_soft_gates=False,
    )
    assert abs(paper.net_edge_bps - live.net_edge_bps) < 1e-6
    assert abs(paper.cost_bps - live.cost_bps) < 1e-6


def test_one_way_impact_would_understate_cost() -> None:
    """Sanity: 1x impact yields higher net edge than 2x — paper must not use 1x."""
    votes = _long_votes()
    one = score_edge_for_desk(
        votes=votes, spread_bps=1.0, impact_bps=2.0, fee_bps=15.0, latency_bps=0.0,
        take_profit_pct=0.55, atr_pct=0.2, regime="trend", mode="paper",
        entry_min_score=0.2, paper_soft_gates=False,
    )
    two = score_edge_for_desk(
        votes=votes, spread_bps=1.0, impact_bps=4.0, fee_bps=15.0, latency_bps=0.0,
        take_profit_pct=0.55, atr_pct=0.2, regime="trend", mode="paper",
        entry_min_score=0.2, paper_soft_gates=False,
    )
    assert one.net_edge_bps > two.net_edge_bps
