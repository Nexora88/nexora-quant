"""Read-only local dashboard and API; do not expose publicly without authentication."""
import asyncio
import hmac
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.responses import HTMLResponse

from app.engine import run, state


DASHBOARD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nexora Quant</title>
<style>
:root{color-scheme:dark;--bg:#080d0b;--panel:#101a15;--line:#20382a;--green:#55f29b;--muted:#92a99b;--red:#ff7e7e}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 10% 0%,#123322 0,transparent 45%),var(--bg);color:#e9f7ee;font:15px system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:auto;padding:28px 18px 60px}.top{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
.brand{font-weight:800;letter-spacing:.04em;font-size:23px}.brand span{color:var(--green)}.sub{color:var(--muted);margin-top:6px}
.pill{border:1px solid #2c6445;background:#10271a;color:var(--green);padding:8px 12px;border-radius:999px;font-size:12px;font-weight:700}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:26px}.card{background:linear-gradient(145deg,#132019,#0e1511);border:1px solid var(--line);border-radius:16px;padding:18px;min-width:0}
.label{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.09em}.value{font-size:clamp(20px,3vw,30px);font-weight:750;margin-top:10px;overflow-wrap:anywhere}.small{color:var(--muted);font-size:12px;margin-top:8px}
.section{margin-top:18px}.section h2{font-size:15px;margin:0 0 12px}.status{display:flex;gap:10px;align-items:center}.dot{width:9px;height:9px;border-radius:50%;background:#64766b}.dot.ok{background:var(--green);box-shadow:0 0 12px #55f29b66}.dot.bad{background:var(--red)}
.row{display:flex;justify-content:space-between;gap:12px;padding:11px 0;border-bottom:1px solid #1d2b22}.row:last-child{border:0}.muted{color:var(--muted)}.warn{color:#ffc66d}.foot{color:#71877a;font-size:12px;line-height:1.7;margin-top:24px}
@media(max-width:760px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}main{padding:20px 12px 40px}}@media(max-width:390px){.grid{grid-template-columns:1fr}}
</style>
</head>
<body><main>
<div class="top"><div><div class="brand">NEXORA <span>QUANT</span></div><div class="sub">Market research · Paper trading · No live orders</div></div><div class="pill">PAPER MODE · LIVE MARKET DATA</div></div>
<div class="grid">
<div class="card"><div class="label">Best bid</div><div class="value" id="bid">—</div><div class="small" id="bidQty">Awaiting feed</div></div>
<div class="card"><div class="label">Best ask</div><div class="value" id="ask">—</div><div class="small" id="askQty">Awaiting feed</div></div>
<div class="card"><div class="label">Paper equity</div><div class="value" id="equity">—</div><div class="small">USDT · simulated account</div></div>
<div class="card"><div class="label">Unrealized PnL</div><div class="value" id="pnl">—</div><div class="small" id="realized">Realized: —</div></div>
</div>
<div class="section card"><h2>System health</h2>
<div class="row"><span class="status"><span id="dot" class="dot"></span><span>Market data feed</span></span><strong id="feed">Waiting</strong></div>
<div class="row"><span>Data age</span><strong id="age">—</strong></div>
<div class="row"><span>Events received</span><strong id="events">0</strong></div>
<div class="row"><span>Risk kill switch</span><strong id="kill">Not active</strong></div>
<div class="row"><span>Paper trades</span><strong id="trades">0</strong></div>
<div class="row"><span>Last update</span><strong id="updated">—</strong></div></div>
<div class="section card"><h2>Paper portfolio</h2>
<div class="row"><span>Available cash</span><strong id="cash">—</strong></div>
<div class="row"><span>Base quantity</span><strong id="qty">—</strong></div>
<div class="row"><span>Average entry</span><strong id="entry">—</strong></div>
<div class="row"><span>Fees paid</span><strong id="fees">—</strong></div></div>
<div class="foot">Research software, not financial advice. Signals are experimental and do not imply profitability. Simulated fills omit realistic slippage, latency, and partial fills. Runtime state is in memory. This dashboard is read-only and should remain on localhost.</div>
</main>
<script>
const el=id=>document.getElementById(id);
const num=(v,d=2)=>v==null?"—":Number(v).toLocaleString(undefined,{maximumFractionDigits:d,minimumFractionDigits:d});
async function refresh(){try{
 const r=await fetch('/status',{cache:'no-store'});const s=await r.json();const m=s.market||{};const p=s.portfolio||{};
 el('decisionAction').textContent=s.last_decision?.action||'Waiting';
 el('regime').textContent=s.last_decision?.regime||s.analysis?.regime||'—';
 el('decisionScore').textContent=s.last_decision?num(s.last_decision.score,3)+' / '+num(s.last_decision.confidence,2):'—';
 el('decisionReason').textContent=[...(s.last_decision?.blockers||[]),...(s.last_decision?.rationale||[])].slice(0,4).join(' · ')||'No decision recorded';
 el('decisionHistory').innerHTML=(s.decision_history||[]).slice(-6).reverse().map(d=>'<div class="row"><span>'+String(d.created_at||'').replace(/[<>]/g,'')+' · '+String(d.action||'').replace(/[<>]/g,'')+'</span><strong>'+num(d.score,2)+' / '+num(d.confidence,2)+'</strong></div>').join('');
 el('fills').innerHTML=(s.recent_fills||[]).slice(0,8).map(t=>'<div class="row"><span>'+String(t.side||'').replace(/[<>]/g,'').toUpperCase()+' · '+num(t.quantity,6)+' @ '+num(t.price,4)+'</span><strong>'+num(t.fee_usdt,4)+' fee</strong></div>').join('')||'<span class="muted">No fills recorded yet</span>';
 el('bid').textContent=num(m.bid,4);el('ask').textContent=num(m.ask,4);
 el('bidQty').textContent='Quantity '+num(m.bid_qty,5);el('askQty').textContent='Quantity '+num(m.ask_qty,5);
 el('equity').textContent=num(p.equity_usdt);el('pnl').textContent=num(p.unrealized_pnl_usdt);
 el('realized').textContent='Realized: '+num(p.realized_pnl_usdt)+' USDT';
 el('cash').textContent=num(p.cash_usdt)+' USDT';el('qty').textContent=num(p.base_quantity,8);
 el('entry').textContent=num(p.average_entry_price,4);el('fees').textContent=num(p.fees_paid_usdt)+' USDT';
 el('events').textContent=s.events_seen??0;el('trades').textContent=p.trade_count??0;
 const ok=Boolean(s.connected);el('feed').textContent=ok?'Receiving data':'Stale / waiting';
 el('dot').className='dot '+(ok?'ok':'bad');el('age').textContent=s.data_age_seconds==null?'—':num(s.data_age_seconds,1)+' s';
 el('kill').textContent=s.kill_switch?(s.kill_switch_reason||'ACTIVE'):'Not active';el('kill').className=s.kill_switch?'warn':'';
 el('updated').textContent=new Date().toLocaleTimeString();
 }catch(e){el('feed').textContent='API unavailable';el('dot').className='dot bad';}}
refresh();setInterval(refresh,2000);
</script></body></html>"""


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(run(), name="nexora-market-engine")
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="Nexora Quant",
    version="0.1.0",
    description="Local read-only dashboard and API for paper trading.",
    lifespan=lifespan,
)

@app.middleware("http")
async def restrict_remote_access(request: Request, call_next):
    """Keep unauthenticated use local-only; remote access requires a bearer token."""
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        expected = os.getenv("NEXORA_API_TOKEN", "")
        supplied = request.headers.get("authorization", "")
        valid = bool(expected) and hmac.compare_digest(
            supplied, "Bearer " + expected
        )
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
    return {"status": "ok", "mode": "paper"}


@app.get("/status")
def status() -> dict:
    return state.snapshot()


@app.get("/portfolio")
def portfolio() -> dict:
    mark = state.latest_book.bid if state.latest_book else None
    return state.executor.snapshot(mark) if state.executor else {"status": "not_started"}
