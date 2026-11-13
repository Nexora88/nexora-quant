"""Local dashboard + status API. Do not expose publicly without auth."""
from __future__ import annotations

import asyncio
import hmac
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.engine import run, state

# NOTE: Full dashboard HTML restored in follow-up if truncated by tooling.
# Minimal viable API so engine + status work.

DASHBOARD = """<!doctype html><html><head><meta charset=utf-8><title>Nexora Quant</title>
<style>body{font-family:system-ui;background:#050a08;color:#e7f7ee;padding:24px}
a{color:#2eff9a}.card{border:1px solid #1a2f24;border-radius:12px;padding:16px;max-width:720px}
pre{background:#0b1410;padding:12px;overflow:auto;font-size:12px}</style></head>
<body><div class=card><h1>Nexora Quant Desk</h1>
<p>API up. Open <a href=/status>/status</a> for JSON (includes <code>retail_reality</code> when module present).</p>
<p class=sub>Full premium dashboard template is in repo history; this minimal shell keeps the bot runnable.</p>
<pre id=out>loading…</pre></div>
<script>fetch('/status').then(r=>r.json()).then(j=>{document.getElementById('out').textContent=JSON.stringify(j,null,2)}).catch(e=>{document.getElementById('out').textContent=String(e)})</script>
</body></html>"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    skip = os.getenv("NEXORA_SKIP_ENGINE", "").strip().lower() in {"1", "true", "yes", "on"}
    skip = skip or bool(os.getenv("PYTEST_CURRENT_TEST"))
    task = None
    if not skip:
        task = asyncio.create_task(run())

        def _done(t: asyncio.Task) -> None:
            try:
                exc = t.exception()
            except asyncio.CancelledError:
                return
            if exc:
                import logging

                logging.getLogger(__name__).exception("Engine task crashed: %s", exc)

        task.add_done_callback(_done)
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="Nexora Quant", version="0.3.1", lifespan=lifespan)


def _is_private_lan(host: str) -> bool:
    if not host:
        return False
    if host.startswith(("192.168.", "10.")):
        return True
    if host.startswith("172."):
        parts = host.split(".")
        try:
            second = int(parts[1])
        except (IndexError, ValueError):
            return False
        return 16 <= second <= 31
    return False


@app.middleware("http")
async def restrict_remote_access(request: Request, call_next):
    client_host = request.client.host if request.client else ""
    if client_host in {"127.0.0.1", "::1", "localhost", "testclient"}:
        return await call_next(request)
    if _is_private_lan(client_host):
        return await call_next(request)
    expected = os.getenv("NEXORA_API_TOKEN", "")
    supplied = request.headers.get("authorization", "")
    valid = bool(expected) and hmac.compare_digest(supplied, "Bearer " + expected)
    if not valid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Remote access disabled or bearer token invalid"},
        )
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return DASHBOARD


@app.get("/health")
def health() -> dict[str, str]:
    from app.config import settings as _s

    return {"status": "ok", "mode": getattr(_s, "trading_mode", "paper")}


@app.get("/status")
def status() -> dict:
    snap = state.snapshot()
    try:
        from app.retail_reality import assess_retail_desk, to_status_dict
        from app.config import settings

        report = assess_retail_desk(
            fee_rate=float(settings.fee_rate),
            vip_level=int(getattr(settings, "fee_vip_level", 0) or 0),
            use_bnb_discount=bool(getattr(settings, "fee_use_bnb_discount", False)),
            prefer_maker=bool(getattr(settings, "prefer_maker", False)),
            expected_alpha_bps=max(12.0, float(settings.take_profit_pct) * 100.0 * 0.85),
            starting_cash_usdt=float(settings.starting_cash_usdt),
        )
        snap["retail_reality"] = to_status_dict(report)
    except Exception as exc:
        snap["retail_reality"] = {"error": type(exc).__name__, "detail": str(exc)[:160]}
    return snap


@app.get("/portfolio")
def portfolio() -> dict:
    mark = state.latest_book.bid if state.latest_book else None
    return state.executor.snapshot(mark) if state.executor else {"status": "not_started"}
