from app.intelligence.memory import TradeMemory


def test_memory_avoids_toxic_setup():
    m = TradeMemory(capacity=50)
    for _ in range(4):
        m.remember(-1.0, regime="stressed", structure="LH_LL_downtrend", motor_bias="short", reason="stop")
    lesson = m.lesson_for(regime="stressed", structure="LH_LL_downtrend", motor_bias="short")
    assert lesson["allow"] is False
    assert lesson["action"] == "avoid"


def test_memory_prefers_proven():
    m = TradeMemory(max_episodes=50)
    for _ in range(5):
        m.remember(0.5, regime="trend", structure="HH_HL_uptrend", motor_bias="long", reason="take_profit")
    lesson = m.lesson_for(regime="trend", structure="HH_HL_uptrend", motor_bias="long")
    assert lesson["allow"] is True
    assert lesson["size_mult"] >= 1.0
    assert lesson["action"] == "prefer"


def test_memory_persist():
    m = TradeMemory()
    m.remember(1.0, regime="trend", structure="HH", motor_bias="long")
    blob = m.export_state()
    m2 = TradeMemory()
    m2.load_state(blob)
    assert m2.to_dict()["lifetime_trades"] == 1
