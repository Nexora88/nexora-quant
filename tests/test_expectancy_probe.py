from app.expectancy import expectancy_probe_policy


def test_expectancy_probe_is_inactive_for_small_or_profitable_samples():
    small = expectancy_probe_policy({"n": 5, "expectancy_usdt": -0.2})
    good = expectancy_probe_policy({"n": 20, "expectancy_usdt": 0.01})
    assert not small.active and small.size_scale == 1.0 and small.score_boost == 0.0
    assert not good.active and good.size_scale == 1.0


def test_negative_expectancy_enters_reduced_risk_probe_instead_of_deadlock():
    policy = expectancy_probe_policy({"n": 12, "expectancy_usdt": -0.15})
    assert policy.active
    assert policy.size_scale == 0.5
    assert policy.score_boost == 0.04
    assert "expectancy_probe" in policy.note
