"""Local read-only API. Do not expose publicly without authentication."""
from fastapi import FastAPI
from app.engine import state

app = FastAPI(title="Nexora Quant", version="0.1.0", description="Read-only status API for paper trading.")

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "paper"}

@app.get("/status")
def status() -> dict:
    return state.snapshot()

@app.get("/portfolio")
def portfolio() -> dict:
    mark = state.latest_book.bid if state.latest_book else None
    return state.executor.snapshot(mark) if state.executor else {"status": "not_started"}
