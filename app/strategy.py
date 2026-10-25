"""Experimental signal logic; this is not a price prediction."""
from app.events import Signal, utc_now

def imbalance_strength(bid_qty: float, ask_qty: float) -> float:
    if bid_qty < 0 or ask_qty < 0:
        raise ValueError("Quote quantities cannot be negative")
    total = bid_qty + ask_qty
    return 0.5 if total == 0 else bid_qty / total

def evaluate_imbalance(bid_qty: float, ask_qty: float, threshold: float = 0.70) -> Signal | None:
    if not 0.5 < threshold <= 1:
        raise ValueError("threshold must be in (0.5, 1]")
    strength = imbalance_strength(bid_qty, ask_qty)
    if strength >= threshold:
        return Signal("buy", "top_of_book_bid_imbalance", strength, utc_now())
    return None
