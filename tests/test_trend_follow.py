from app.intelligence.trend_follow import TrendFollower


def test_uptrend_allows_long():
    t = TrendFollower(fast=5, slow=10)
    for i in range(20):
        t.push(100 + i * 0.5)
    st = t.state()
    assert st.allow_long is True
    assert st.alignment == "up"


def test_downtrend_blocks_long():
    t = TrendFollower(fast=5, slow=10)
    for i in range(20):
        t.push(200 - i * 0.5)
    st = t.state()
    assert st.allow_long is False
