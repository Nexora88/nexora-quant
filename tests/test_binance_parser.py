import json
from app.binance_ws import parse_message
from app.events import BookTicker, TradeTick, KlineTick

def test_parses_combined_stream_book_ticker():
    message = json.dumps({"stream":"btcusdt@bookTicker","data":{"e":"bookTicker","s":"BTCUSDT","b":"100.0","B":"2.0","a":"100.1","A":"3.0"}})
    event = parse_message(message)
    assert isinstance(event, BookTicker)
    assert event.symbol == "btcusdt"
    assert event.bid == 100.0 and event.ask == 100.1

def test_parses_trade_event():
    message = json.dumps({"e":"trade","s":"BTCUSDT","p":"100.2","q":"0.3","m":True})
    event = parse_message(message)
    assert isinstance(event, TradeTick)
    assert event.price == 100.2
    assert event.buyer_is_maker


def test_parses_closed_kline_event():
    message = json.dumps({
        "stream": "btcusdt@kline_1m",
        "data": {
            "e": "kline", "s": "BTCUSDT",
            "k": {
                "i": "1m", "t": 1700000000000,
                "o": "100.0", "h": "101.0", "l": "99.5",
                "c": "100.5", "v": "42.0", "x": True,
            },
        },
    })
    event = parse_message(message)
    assert isinstance(event, KlineTick)
    assert event.symbol == "btcusdt"
    assert event.interval == "1m"
    assert event.closed
    assert event.close == 100.5
