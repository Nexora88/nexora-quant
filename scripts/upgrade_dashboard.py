"""Local dashboard + status API. Do not expose publicly without auth."""
from __future__ import annotations

import asyncio
import hmac
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.engine import run, state

DASHBOARD = """<!doctype html>
<html lang=\"tr\"><head>
<meta charset=\"utf-8\"/><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"/>
<title>Nexora Quant Desk</title>
<style>
:root{--bg:#050a08;--card:#0e1a14;--line:#1a2f24;--g:#2eff9a;--r:#ff4d6a;--a:#ffc14d;--m:#7f9a8c;--t:#e7f7ee}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t);font:13px/1.45 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:14px 12px 40px}
.top{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:12px}
.brand{font-size:18px;font-weight:800;letter-spacing:.04em}.brand span{color:var(--g)}
.sub{color:var(--m);font-size:11px;margin-top:2px}
.eq{font-size:28px;font-weight:800;color:var(--g);text-align:right}.eq.neg{color:var(--r)}
.pills{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.pill{border:1px solid var(--line);padding:3px 9px;border-radius:999px;font-size:10px;font-weight:700;color:var(--g)}
.pill.off{color:var(--r);border-color:#4a2030}.pill.warn{color:var(--a)}
.grid{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-bottom:10px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px}
.stat .l{color:var(--m);font-size:10px;text-transform:uppercase}.stat .v{font-size:16px;font-weight:700;margin-top:3px}
.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px;margin-bottom:10px}
h2{margin:0 0 8px;font-size:11px;color:#cfe8d8;text-transform:uppercase;letter-spacing:.05em}
.pos{color:var(--g)}.neg{color:var(--r)}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:5px 4px;border-bottom:1px solid #152018;text-align:left}
th{color:var(--m);font-size:10px}
.why div{padding:3px 0;border-bottom:1px solid #152018;font-size:12px}
.log{font-family:ui-monospace,monospace;font-size:11px;max-height:140px;overflow:auto;background:#070e0b;border:1px solid var(--line);border-radius:10px;padding:8px;color:#9bbfad}
.foot{text-align:center;color:var(--m);font-size:11px;margin-top:14px}
@media(max-width:800px){.grid{grid-template-columns:repeat(3,1fr)}.row{grid-template-columns:1fr}}
</style></head><body><main>
<div class=\"top\">
  <div><div class=\"brand\">NEXORA <span>QUANT</span></div>
  <div class=\"sub\">Fee-aware Spot L2 · paper / live · edge yoksa trade yok</div>
  <div class=\"pills\" id=\"pills\"></div></div>
  <div><div class=\"sub\" style=\"text-align:right\">Equity</div><div class=\"eq\" id=\"eq\">—</div>
  <div class=\"sub\" id=\"eqsub\" style=\"text-align:right\">—</div></div>
</div>
<div class=\"grid\">
  <div class=\"stat\"><div class=\"l\">Sembol</div><div class=\"v\" id=\"sym\">—</div></div>
  <div class=\"stat\"><div class=\"l\">Skor</div><div class=\"v\" id=\"sc\">—</div></div>
  <div class=\"stat\"><div class=\"l\">Net PnL</div><div class=\"v\" id=\"net\">—</div></div>
  <div class=\"stat\"><div class=\"l\">İşlem</div><div class=\"v\" id=\"tc\">0</div></div>
  <div class=\"stat\"><div class=\"l\">Session PnL</div><div class=\"v\" id=\"spnl\">—</div></div>
  <div class=\"stat\"><div class=\"l\">Posture</div><div class=\"v\" id=\"posture\">—</div></div>
</div>
<div class=\"row\">
  <div class=\"card\"><h2>Neden / blockers</h2><div class=\"why\" id=\"why\"></div>
    <h2 style=\"margin-top:10px\">Retail reality</h2><div class=\"why\" id=\"reality\"></div></div>
  <div class=\"card\"><h2>Son filller</h2>
    <table><thead><tr><th>Saat</th><th>Yön</th><th>Fiyat</th><th>PnL</th><th>Fee</th></tr></thead>
    <tbody id=\"fills\"></tbody></table>
    <h2 style=\"margin-top:10px\">Log</h2><div class=\"log\" id=\"log\"></div></div>
</div>
<div class=\"foot\">Garanti kâr yok · fee round-trip · investment advice değil</div>
</main>
<script>
const el=id=>document.getElementById(id);
const num=(x,d=2)=>{const n=Number(x);return Number.isFinite(n)?n.toFixed(d):'—'};
async function tick(){
  try{
    const s=await(await fetch('/status')).json();
    const p=s.portfolio||{},a=s.analysis||{},d=s.last_decision||{};
    const eq=Number(p.equity_usdt||p.cash_usdt||0);
    const start=Number(p.starting_cash_usdt||100);
    const realized=Number(p.realized_pnl_usdt||0);
    el('eq').textContent=num(eq,2)+' USDT';
    el('eq').className='eq'+(eq<start?' neg':'');
    el('eqsub').textContent='realized '+num(realized,3)+' · fees '+num(p.fees_paid_usdt,3);
    el('sym').textContent=String(s.symbol||'—').toUpperCase();
    el('sc').textContent=num(a.score,2);
    el('net').textContent=num(realized,3);
    el('net').className='v '+(realized>=0?'pos':'neg');
    el('tc').textContent=String(p.trade_count||0);
    const sp=Number(s.session_realized_pnl_usdt||0);
    el('spnl').textContent=num(sp,3);
    el('spnl').className='v '+(sp>=0?'pos':'neg');
    const exp=s.session_expectancy||{};
    const ms=s.maker_stats||{};
    const expN=Number(exp.n||0);
    let extra='';
    if(expN>0){
      extra+=' · exp '+num(exp.expectancy_usdt,3)+' ('+expN+'x, wr '+num((exp.win_rate||0)*100,0)+'%)';
    }
    if(ms.attempts){
      extra+=' · maker '+(ms.fills||0)+'/'+ms.attempts+(ms.timeout_rate!=null?' to '+num(ms.timeout_rate*100,0)+'%':'');
      if(ms.weak_maker_path) extra+=' ⚠';
    }
    el('eqsub').textContent='realized '+num(realized,3)+' · fees '+num(p.fees_paid_usdt,3)+extra;
    const rr=s.retail_reality||{};
    el('posture').textContent=rr.posture||'—';
    const pills=[];
    pills.push('<span class=\"pill \"'+(s.connected?'':'off')+'\">'+(s.connected?'LIVE L2':'L2 KOPUK')+'</span>');
    pills.push('<span class=\"pill\">'+(s.mode||'paper').toUpperCase()+'</span>');
    if(s.kill_switch)pills.push('<span class=\"pill off\">KILL</span>');
    el('pills').innerHTML=pills.join('');
    const blockers=d.blockers||s.blockers_live||[];
    const rat=d.rationale||[];
    const why=[...blockers.map(x=>'⛔ '+x),...rat.slice(0,6).map(x=>'· '+x)];
    el('why').innerHTML=why.length?why.slice(0,12).map(t=>'<div>'+String(t).replace(/[<>]/g,'')+'</div>').join(''):'<div class=\"pos\">Engelsiz — edge bekleniyor olabilir</div>';
    const rec=rr.recommendations||[];
    el('reality').innerHTML='<div>'+String(rr.summary||'—').replace(/[<>]/g,'')+'</div>'+rec.slice(0,5).map(x=>'<div>· '+String(x).replace(/[<>]/g,'')+'</div>').join('');
    const fills=s.recent_fills||[];
    el('fills').innerHTML=fills.length?fills.slice(0,12).map(t=>{
      const pnl=Number(t.pnl_usdt);const side=String(t.side||'').toUpperCase();
      return '<tr><td>'+String(t.timestamp||'').slice(11,19)+'</td><td class=\"'+(side.includes('BUY')||side==='LONG'?'pos':'neg')+'\">'+side+'</td><td>'+num(t.price,2)+'</td><td class=\"'+(pnl>=0?'pos':'neg')+'\">'+num(pnl,3)+'</td><td>'+num(t.fee_usdt,4)+'</td></tr>';
    }).join(''):'<tr><td colspan=\"5\" style=\"color:#7f9a8c\">Fill yok — edge + fee kapısı bekleniyor</td></tr>';
    const logs=s.live_log||[];
    el('log').innerHTML=logs.length?logs.slice(0,20).map(x=>'<div>'+String(x).replace(/[<>]/g,'')+'</div>').join(''):'<div>log boş</div>';
  }catch(e){console.warn(e)}
}
setInterval(tick,1000);tick();
</script></body></html>
"""


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


app = FastAPI(title="Nexora Quant", version="0.3.2", lifespan=lifespan)


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
