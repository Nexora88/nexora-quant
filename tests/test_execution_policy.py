from app.execution_policy import maker_route_enabled


def test_paper_never_claims_a_maker_route_even_when_prefer_maker_is_set():
    assert maker_route_enabled("paper", True) is False


def test_live_maker_route_requires_explicit_preference():
    assert maker_route_enabled("live", True) is True
    assert maker_route_enabled("live", False) is False
