from app.microstructure_costs import ObservedExecutionCostModel


def test_cost_model_fails_closed_until_enough_real_samples():
    model = ObservedExecutionCostModel(min_samples=3, horizon_ms=10)
    assert model.estimate_cost_bps() is None
    for i in range(2):
        model.record_fill(
            side="buy", decision_mid=100, fill_price=100.1,
            latency_ms=50, filled_at_ms=i * 100,
        )
        model.observe_mid(99.9, i * 100 + 11)
    assert model.estimate_cost_bps() is None


def test_cost_model_calibrates_from_fill_and_post_fill_mid():
    model = ObservedExecutionCostModel(min_samples=3, horizon_ms=10)
    for i in range(3):
        model.record_fill(
            side="buy", decision_mid=100, fill_price=100.1,
            latency_ms=50 + i, filled_at_ms=i * 100,
        )
        model.observe_mid(99.9, i * 100 + 11)
    estimated_latency = model.estimate_latency_ms()
    assert estimated_latency is not None and estimated_latency >= 50
    estimate = model.estimate_cost_bps(latency_ms=estimated_latency)
    assert estimate is not None
    assert estimate > 0


def test_sell_adverse_move_is_directional():
    model = ObservedExecutionCostModel(min_samples=2, horizon_ms=10)
    for i in range(2):
        model.record_fill(
            side="sell", decision_mid=100, fill_price=100,
            latency_ms=20, filled_at_ms=i * 100,
        )
        model.observe_mid(101, i * 100 + 11)
    assert model.estimate_cost_bps() == 100.0


def test_invalid_fill_is_rejected():
    model = ObservedExecutionCostModel()
    try:
        model.record_fill(
            side="buy", decision_mid=0, fill_price=100,
            latency_ms=10, filled_at_ms=0,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("invalid fill must be rejected")


def test_calibration_survives_restart_and_restores_pending_fills(tmp_path):
    path = tmp_path / "state" / "execution-costs.json"
    model = ObservedExecutionCostModel(
        min_samples=3, horizon_ms=10, persistence_path=path,
    )
    for i in range(2):
        model.record_fill(
            side="buy", decision_mid=100, fill_price=100.1,
            latency_ms=50 + i, filled_at_ms=i * 100,
        )
        model.observe_mid(99.9, i * 100 + 11)
    model.record_fill(
        side="sell", decision_mid=100, fill_price=99.9,
        latency_ms=80, filled_at_ms=300,
    )

    restarted = ObservedExecutionCostModel(
        min_samples=3, horizon_ms=10, persistence_path=path,
    )
    assert restarted.sample_count == 2
    assert len(restarted.pending) == 1
    assert restarted.estimate_cost_bps() is None

    restarted.observe_mid(99.8, 311)
    assert restarted.sample_count == 3
    assert restarted.estimate_cost_bps() is not None

    restarted_again = ObservedExecutionCostModel(
        min_samples=3, horizon_ms=10, persistence_path=path,
    )
    assert restarted_again.sample_count == 3
    assert restarted_again.estimate_cost_bps() == restarted.estimate_cost_bps()


def test_corrupt_or_mismatched_calibration_fails_closed(tmp_path):
    path = tmp_path / "execution-costs.json"
    path.write_text('{"schema_version":999,"samples":[{"latency_ms":1,"cost_bps":1}]}')
    model = ObservedExecutionCostModel(
        min_samples=2, horizon_ms=10, persistence_path=path,
    )
    assert model.sample_count == 0
    assert model.estimate_cost_bps() is None
