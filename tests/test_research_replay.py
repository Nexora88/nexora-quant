from app.research_replay import replay_orders


def test_replay_uses_book_after_latency_and_cancel():
    events = [
        {"timestamp_ns": 1, "event_type": "depth", "payload": {
            "bids": [[99, 5]], "asks": [[100, 2], [101, 4]],
        }},
        {"timestamp_ns": 3, "event_type": "cancel", "payload": {
            "side": "ask", "price": 100, "quantity": 2,
        }},
    ]
    result = replay_orders(events, [{"timestamp_ns": 1, "side": "buy", "quantity": 3}],
                           latency_ns=2, fee_rate=0.001)
    assert result[0]["filled_quantity"] == 3
    assert result[0]["vwap"] == 101
    assert result[0]["fees"] == 303 * 0.001


def test_replay_caps_to_visible_liquidity_and_charges_fee():
    events = [{"timestamp_ns": 1, "event_type": "depth", "payload": {
        "bids": [[99, 1]], "asks": [[100, 1]],
    }}]
    result = replay_orders(events, [{"timestamp_ns": 1, "side": "buy", "quantity": 3}])
    assert result[0]["filled_quantity"] == 1
    assert result[0]["remaining_quantity"] == 2
    assert result[0]["fees"] == 0.1


def test_replay_empty_book_does_not_fill():
    result = replay_orders([], [{"timestamp_ns": 1, "side": "sell", "quantity": 1}])
    assert result[0]["filled_quantity"] == 0
    assert result[0]["vwap"] is None
