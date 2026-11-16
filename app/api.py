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
:root{color-scheme:dark;--bg:#070b0a;--surface:#0d1512;--surface-2:#111d18;--line:#20372b;--line-soft:#17271f;--green:#42f5a1;--green-soft:#a3f5c9;--red:#ff647c;--amber:#f5c46b;--muted:#8ba596;--text:#e9f5ee;--shadow:0 18px 48px rgba(0,0,0,.24)}
*{box-sizing:border-box}
html{min-height:100%;background:var(--bg);-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 14% -8%,rgba(48,135,91,.15),transparent 34%),radial-gradient(ellipse at 100% 0,rgba(41,93,71,.10),transparent 28%),var(--bg);color:var(--text);font:13px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Arial,sans-serif;letter-spacing:.005em}
main{width:min(1180px,100%);margin:0 auto;padding:24px 20px 42px}
.top{display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap;padding:18px 20px;margin-bottom:14px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(120deg,rgba(17,32,24,.96),rgba(10,19,15,.96));box-shadow:var(--shadow)}
.brand{font-size:19px;font-weight:850;letter-spacing:.12em}.brand span{color:var(--green)}
.sub{color:var(--muted);font-size:11px;margin-top:4px;letter-spacing:.025em}
.eq{font-size:clamp(25px,4vw,34px);font-weight:800;line-height:1.15;color:var(--green);text-align:right;font-variant-numeric:tabular-nums}
.eq.neg{color:var(--red)}
.pills{display:flex;flex-wrap:wrap;gap:7px;margin-top:12px}
.pill{display:inline-flex;align-items:center;gap:6px;border:1px solid rgba(66,245,161,.24);background:rgba(66,245,161,.07);padding:4px 10px;border-radius:999px;font-size:10px;font-weight:750;letter-spacing:.06em;color:var(--green-soft)}
.pill.off{color:var(--red);border-color:rgba(255,100,124,.28);background:rgba(255,100,124,.07)}.pill.warn{color:var(--amber);border-color:rgba(245,196,107,.25)}
.grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin-bottom:12px}
.stat{position:relative;overflow:hidden;min-width:0;background:linear-gradient(145deg,var(--surface-2),var(--surface));border:1px solid var(--line);border-radius:14px;padding:13px 14px;box-shadow:0 8px 22px rgba(0,0,0,.12)}
.stat:after{content:"";position:absolute;left:0;top:0;bottom:0;width:2px;background:rgba(66,245,161,.36)}
.stat .l{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.11em;font-weight:750}
.stat .v{overflow-wrap:anywhere;font-size:clamp(15px,2vw,19px);font-weight:760;margin-top:7px;font-variant-numeric:tabular-nums}
.row{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}
.card{min-width:0;background:linear-gradient(155deg,rgba(15,26,20,.98),rgba(10,17,14,.98));border:1px solid var(--line);border-radius:16px;padding:16px;margin-bottom:12px;box-shadow:var(--shadow)}
h2{display:flex;align-items:center;gap:8px;margin:0 0 12px;font-size:10px;color:#cce9d8;text-transform:uppercase;letter-spacing:.12em;font-weight:800}
h2:before{content:"";width:6px;height:6px;border-radius:2px;background:var(--green);box-shadow:0 0 12px rgba(66,245,161,.35)}
.pos{color:var(--green)}.neg{color:var(--red)}
table{width:100%;border-collapse:collapse;font-size:11px;font-variant-numeric:tabular-nums}
th,td{padding:9px 7px;border-bottom:1px solid var(--line-soft);text-align:left;white-space:nowrap}
th{color:var(--muted);font-size:9px;letter-spacing:.09em;text-transform:uppercase;font-weight:750}
tbody tr:hover{background:rgba(66,245,161,.035)}
.why div{padding:7px 8px;margin:3px 0;border:1px solid var(--line-soft);border-radius:8px;background:rgba(255,255,255,.012);font-size:11px;overflow-wrap:anywhere}
.log{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:10px;line-height:1.6;max-height:170px;overflow:auto;background:#070e0b;border:1px solid var(--line);border-radius:10px;padding:10px;color:#a8c6b5;overflow-wrap:anywhere}
.foot{text-align:center;color:var(--muted);font-size:10px;margin-top:18px;padding:12px;border-top:1px solid var(--line-soft);letter-spacing:.04em}
@media(max-width:900px){main{padding:16px 14px 30px}.grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:620px){main{padding:10px 10px 24px}.top{padding:15px;border-radius:14px;gap:14px}.top>div:last-child{width:100%;display:flex;align-items:baseline;justify-content:space-between;gap:8px}.top>div:last-child .sub{text-align:left!important}.eq{text-align:right;font-size:25px}.grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.stat{padding:11px 12px}.row{grid-template-columns:minmax(0,1fr);gap:0}.card{padding:13px;border-radius:13px}th,td{padding:8px 5px;font-size:10px}.foot{font-size:9px}}
@media(prefers-reduced-motion:no-preference){.stat,.card,.pill{transition:border-color .18s ease,transform .18s ease}.stat:hover{border-color:rgba(66,245,161,.38);transform:translateY(-1px)}}
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
def dashboard() -> HTMLResponse:
    # Explicit UTF-8 response header keeps Turkish glyphs stable across browsers/proxies.
    return HTMLResponse(
        content=DASHBOARD,
        headers={"Content-Type": "text/html; charset=utf-8"},
    )


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
