import json
from app.binance_ws import parse_message
from app.events import BookTicker, TradeTick

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
