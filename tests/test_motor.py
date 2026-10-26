from app.analytics.motor import AnalysisMotor


def test_motor_uptrend_bias():
    m = AnalysisMotor(window=80, ema_alpha=0.5, enter_threshold=0.15, exit_threshold=0.05)
    for i in range(40):
        m.push_mid(100 + i * 0.3)
    rep = m.evaluate(weighted_obi=0.4, micro_premium_bps=2.0, regime="trend")
    assert rep.bias in ("long", "neutral")
    assert rep.fused_score > -0.1
    assert len(rep.votes) >= 5


def test_motor_downtrend_not_long():
    m = AnalysisMotor(window=80, ema_alpha=0.5, enter_threshold=0.15, exit_threshold=0.05)
    for i in range(40):
        m.push_mid(200 - i * 0.4)
    rep = m.evaluate(weighted_obi=-0.3, micro_premium_bps=-2.0, regime="trend")
    assert rep.bias in ("short", "neutral")


def test_motor_hysteresis_stable():
    m = AnalysisMotor(window=80, ema_alpha=0.35, enter_threshold=0.25, exit_threshold=0.08)
    for i in range(30):
        m.push_mid(100 + i * 0.5)
    rep1 = m.evaluate(weighted_obi=0.5, micro_premium_bps=3.0, regime="trend")
    for i in range(5):
        m.push_mid(115 - i * 0.05)
    rep2 = m.evaluate(weighted_obi=0.1, micro_premium_bps=0.2, regime="trend")
    if rep1.bias == "long":
        assert rep2.bias in ("long", "neutral")


def test_motor_export_load_roundtrip():
    m = AnalysisMotor(window=60)
    for i in range(25):
        m.push_mid(50 + i * 0.2)
    m.evaluate(weighted_obi=0.2, regime="trend")
    blob = m.export_state()
    m2 = AnalysisMotor(window=60)
    m2.load_state(blob)
    assert m2._bias == m._bias
    assert abs(m2._ema_fused - m._ema_fused) < 1e-9
    assert len(m2._mids) >= 10


def test_history_vote_present():
    m = AnalysisMotor(window=80)
    for i in range(30):
        m.push_mid(100 + i * 0.1)
    rep = m.evaluate()
    names = [v.name for v in rep.votes]
    assert "history" in names
