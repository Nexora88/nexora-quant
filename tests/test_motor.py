from app.analytics.motor import AnalysisMotor


def test_motor_uptrend_bias():
    m = AnalysisMotor(window=80)
    for i in range(40):
        m.push_mid(100 + i * 0.3)
    rep = m.evaluate(weighted_obi=0.4, micro_premium_bps=2.0, regime="trend")
    assert rep.bias in ("long", "neutral")
    assert rep.fused_score > -0.1
    assert len(rep.votes) >= 4


def test_motor_downtrend_not_long():
    m = AnalysisMotor(window=80)
    for i in range(40):
        m.push_mid(200 - i * 0.4)
    rep = m.evaluate(weighted_obi=-0.3, micro_premium_bps=-2.0, regime="trend")
    assert rep.bias in ("short", "neutral")
