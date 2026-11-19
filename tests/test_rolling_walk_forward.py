from scripts.rolling_walk_forward import rolling_bounds


def test_rolling_windows_are_chronological_and_non_overlapping():
    bounds = rolling_bounds(1000, 3)
    assert len(bounds) == 3
    previous_test_end = None
    for train_end, test_start, test_end in bounds:
        assert train_end == test_start
        if previous_test_end is not None:
            assert train_end == previous_test_end
        assert test_end > test_start
        previous_test_end = test_end


def test_rolling_windows_reject_too_short_history():
    import pytest

    with pytest.raises(ValueError):
        rolling_bounds(100, 2)
