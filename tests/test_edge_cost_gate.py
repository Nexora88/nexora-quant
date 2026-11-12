from app.decision import FeatureVote
from app.intelligence.edge import estimate_alpha_bps, score_edge


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
    report = score_edge(votes=[], spread_bps=-1, impact_bps=-2)
    assert report.cost_bps >= 0
    assert "clamped_negative_cost_inputs" in report.notes
    assert not report.tradeable


def test_paper_soft_min_net_edge_allowed():
    votes = [FeatureVote("obi", "long", 1.0, 0.9, "strong")]
    report = score_edge(
        votes=votes, spread_bps=1, impact_bps=1, fee_bps=2,
        expected_alpha_bps=15, min_quality=0.2, min_net_edge_bps=-4.0,
        paper_soft_gates=True,
    )
    assert report.tradeable
    assert "paper_soft_gates" in report.notes


def test_live_does_not_cap_strict_gates(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("PAPER_SOFT_GATES", "false")
    votes = [FeatureVote("obi", "long", 1.0, 0.5, "weak agreement")]
    report = score_edge(
        votes=votes, spread_bps=1, impact_bps=1, fee_bps=2,
        expected_alpha_bps=15, min_quality=0.50, min_net_edge_bps=2.0,
        paper_soft_gates=False,
    )
    assert "paper_soft_gates" not in report.notes
    blocked = score_edge(
        votes=votes, spread_bps=5, impact_bps=5, fee_bps=10,
        expected_alpha_bps=15, min_quality=0.10, min_net_edge_bps=5.0,
        paper_soft_gates=False,
    )
    assert not blocked.tradeable


def test_estimate_alpha_scales_with_tp_and_regime():
    quiet = estimate_alpha_bps(take_profit_pct=0.55, atr_pct=0.001, regime="range")
    trend = estimate_alpha_bps(take_profit_pct=0.55, atr_pct=0.001, regime="trend_up")
    assert quiet >= 8.0
    assert trend >= quiet * 0.99
    wide = estimate_alpha_bps(take_profit_pct=1.2, atr_pct=0.01, regime="breakout")
    assert wide > quiet
