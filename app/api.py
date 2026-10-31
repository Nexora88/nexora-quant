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
<html lang=\"tr\">
<head>
<meta charset=\"utf-8\"/>
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"/>
<title>Nexora Quant</title>
<style>
:root{--bg:#070b09;--card:#0e1612;--line:#1c2e24;--g:#3dff9a;--r:#ff5c6c;--a:#ffd166;--m:#8aa896;--t:#e8f6ee}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(900px 400px at 15% -10%,#12322555,transparent),var(--bg);color:var(--t);font:14px/1.45 system-ui,Segoe UI,sans-serif}
main{max-width:1180px;margin:0 auto;padding:16px 14px 40px}
.top{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;margin-bottom:14px}
.brand{font-size:22px;font-weight:800;letter-spacing:.04em}.brand b{color:var(--g)}
.sub{color:var(--m);font-size:12px;margin-top:2px}
.pnl{font-size:32px;font-weight:800;font-variant-numeric:tabular-nums;color:var(--g);text-shadow:0 0 20px #3dff9a44}
.pills{display:flex;flex-wrap:wrap;gap:6px}
.pill{border:1px solid var(--line);background:#0c1812;color:var(--g);padding:5px 10px;border-radius:999px;font-size:11px;font-weight:700}
.pill.off{color:var(--r);border-color:#4a2030;background:#1a0c10}
.pill.warn{color:var(--a);border-color:#4a3a10}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.card{background:linear-gradient(165deg,#121c17,#0b120e);border:1px solid var(--line);border-radius:14px;padding:12px 14px}
.lbl{color:var(--m);font-size:11px;text-transform:uppercase;letter-spacing:.07em}
.val{font-size:20px;font-weight:750;margin-top:6px;font-variant-numeric:tabular-nums}
.row{display:grid;grid-template-columns:1fr 1.15fr 1fr;gap:10px;margin-top:10px}
h2{margin:0 0 8px;font-size:13px;color:#cfe8d8}
.gauge-wrap{display:flex;align-items:center;justify-content:center;height:130px}
.gauge{width:140px;height:140px;border-radius:50%;display:grid;place-items:center;position:relative}
.gauge::after{content:\"\";position:absolute;inset:12px;border-radius:50%;background:#0a100e}
.gauge span{position:relative;z-index:1;font-size:26px;font-weight:800}
.bar{height:8px;background:#152019;border-radius:6px;overflow:hidden;margin-top:8px}.bar>i{display:block;height:100%;width:0;background:linear-gradient(90deg,#1a6b45,var(--g));transition:width .3s}
.log{font-family:ui-monospace,Consolas,monospace;font-size:11px;max-height:200px;overflow:auto;background:#070c0a;border:1px solid var(--line);border-radius:10px;padding:8px}
.log div{padding:5px 0;border-bottom:1px solid #152019;color:#b7d0c2}
.log .bad{color:var(--r)}.log .ok{color:var(--g)}
canvas{width:100%;height:120px;background:#070c0a;border-radius:10px;border:1px solid var(--line)}
.table{width:100%;border-collapse:collapse;font-size:12px}
.table th,.table td{text-align:left;padding:6px 4px;border-bottom:1px solid #152019}
.pos{color:var(--g)}.neg{color:var(--r)}
.foot{margin-top:16px;color:#6d8578;font-size:12px;line-height:1.5}
@media(max-width:900px){.grid,.row{grid-template-columns:1fr 1fr}}
@media(max-width:520px){.grid,.row{grid-template-columns:1fr}}
</style>
</head>
<body>
<main>
  <div class=\"top\">
    <div>
      <div class=\"brand\">NEXORA <b>QUANT</b></div>
      <div class=\"sub\">Paper desk · canlı L2 · seçici giriş (fee sonrası net)</div>
    </div>
    <div class=\"pnl\" id=\"pnl\">$0.00</div>
    <div class=\"pills\">
      <span class=\"pill\" id=\"mode\">—</span>
      <span class=\"pill\" id=\"sym\">—</span>
      <span class=\"pill\" id=\"conn\">—</span>
      <span class=\"pill\" id=\"act\">—</span>
    </div>
  </div>
  <div class=\"grid\">
    <div class=\"card\"><div class=\"lbl\">Equity</div><div class=\"val\" id=\"eq\">—</div><div class=\"lbl\" id=\"fees\">—</div></div>
    <div class=\"card\"><div class=\"lbl\">Fiyat (mid)</div><div class=\"val\" id=\"mid\">—</div><div class=\"lbl\" id=\"spr\">—</div></div>
    <div class=\"card\"><div class=\"lbl\">Skor / eşik</div><div class=\"val\" id=\"sc\">—</div><div class=\"lbl\" id=\"reg\">—</div></div>
    <div class=\"card\"><div class=\"lbl\">Karar</div><div class=\"val\" id=\"dec\">—</div><div class=\"lbl\" id=\"ev\">—</div></div>
  </div>
  <div class=\"row\">
    <div class=\"card\">
      <h2>Sinyal skometresi</h2>
      <div class=\"gauge-wrap\"><div class=\"gauge\" id=\"gauge\"><span id=\"gval\">0.00</span></div></div>
      <div class=\"bar\"><i id=\"gbar\"></i></div>
      <div class=\"lbl\" style=\"margin-top:8px\" id=\"gmsg\">eşik altı = bekle</div>
    </div>
    <div class=\"card\">
      <h2>Neden işlem yok / var?</h2>
      <div class=\"log\" id=\"why\"><div>Yükleniyor…</div></div>
    </div>
    <div class=\"card\">
      <h2>Oylar (votes)</h2>
      <div class=\"log\" id=\"votes\"><div>—</div></div>
    </div>
  </div>
  <div class=\"row\" style=\"grid-template-columns:1fr 1fr;margin-top:10px\">
    <div class=\"card\">
      <h2>Fiyat (son tickler)</h2>
      <canvas id=\"pc\" width=\"560\" height=\"120\"></canvas>
    </div>
    <div class=\"card\">
      <h2>Equity eğrisi</h2>
      <canvas id=\"ec\" width=\"560\" height=\"120\"></canvas>
    </div>
  </div>
  <div class=\"card\" style=\"margin-top:10px\">
    <h2>Son paper işlemler</h2>
    <table class=\"table\">
      <thead><tr><th>saat</th><th>side</th><th>qty</th><th>px</th><th>pnl</th><th>fee</th></tr></thead>
      <tbody id=\"fills\"><tr><td colspan=\"6\" class=\"lbl\">Henüz işlem yok</td></tr></tbody>
    </table>
  </div>
  <div class=\"foot\">Motor mahvolmadı: events artıyorsa L2 akıyor. Skor < eşik veya negatif edge iken long açılmaz (kasıtlı).</div>
</main>
<script>
const el=id=>document.getElementById(id);
const num=(v,d=2)=>{const n=Number(v);return Number.isFinite(n)?n.toFixed(d):'—'};
function setGauge(score, minScore){
  const s=Math.max(0,Math.min(1,Number(score)||0));
  const ok=s>=(minScore||0.38);
  const col=ok?'#3dff9a':(s>=0.2?'#ffd166':'#3a5a48');
  const deg=Math.round(s*360);
  el('gauge').style.background=`conic-gradient(${col} 0deg,${col} ${deg}deg,#1a2e24 ${deg}deg)`;
  el('gval').textContent=num(score,2);
  el('gbar').style.width=Math.round(s*100)+'%';
  el('gmsg').textContent=ok?'TRADE band — diğer filtreler de yeşil olmalı':'eşik altı / edge yok → bekle';
}
function drawLine(canvasId, points, key, color){
  const c=el(canvasId); if(!c) return;
  const ctx=c.getContext('2d');
  const w=c.width, h=c.height;
  ctx.clearRect(0,0,w,h);
  if(!points||points.length<2){ctx.fillStyle='#6d8578'; ctx.fillText('veri yok',12,h/2); return;}
  const ys=points.map(p=>Number(p[key])).filter(Number.isFinite);
  if(!ys.length) return;
  let min=Math.min(...ys), max=Math.max(...ys);
  if(min===max){min-=1; max+=1}
  ctx.strokeStyle=color; ctx.lineWidth=2; ctx.beginPath();
  points.forEach((p,i)=>{
    const yv=Number(p[key]); if(!Number.isFinite(yv)) return;
    const x=i/(points.length-1)*(w-8)+4;
    const y=h-4-((yv-min)/(max-min))*(h-8);
    if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
  });
  ctx.stroke();
}
async function tick(){
  try{
    const r=await fetch('/status',{cache:'no-store'});
    const s=await r.json();
    const m=s.market||{}, a=s.analysis||{}, p=s.portfolio||{}, d=s.last_decision||{};
    const minSc=Number((s.risk_limits&&s.risk_limits.entry_min_score)||0.38);
    el('mode').textContent=String(s.mode||'paper').toUpperCase();
    el('sym').textContent=String(s.symbol||m.symbol||'—').toUpperCase();
    el('conn').textContent=s.connected?'LIVE L2':'kopuk';
    el('conn').className='pill'+(s.connected?'':' off');
    const act=String(d.action||'—');
    el('act').textContent=act.toUpperCase();
    el('act').className='pill'+(act==='block'||act==='hold'?' warn':'');
    const real=Number(p.realized_pnl_usdt||0);
    el('pnl').textContent='$'+(Number.isFinite(real)?real.toFixed(2):'0.00');
    el('pnl').style.color=real>=0?'#3dff9a':'#ff5c6c';
    el('eq').textContent=num(p.equity_usdt)+' USDT';
    el('fees').textContent='fee '+num(p.fees_paid_usdt,4)+' · trades '+(p.trade_count||0);
    el('mid').textContent=num(a.mid||((Number(m.bid)+Number(m.ask))/2),2);
    el('spr').textContent='spread '+num(a.spread_bps,3)+' bps';
    const score=Number(a.score!=null?a.score:(d.score!=null?d.score:0));
    el('sc').textContent=num(score,2)+' / '+num(minSc,2);
    el('reg').textContent=(a.regime||d.regime||'—')+' · OBI '+num(a.weighted_obi,2);
    el('dec').textContent=act;
    el('ev').textContent='events '+(s.events_seen||0);
    setGauge(score, minSc);
    const blockers=d.blockers||[];
    const rat=d.rationale||[];
    const why=[...blockers.map(x=>'⛔ '+x), ...rat.map(x=>'· '+x)];
    el('why').innerHTML=why.length?why.slice(0,12).map(t=>'<div class=\"'+(String(t).includes('⛔')?'bad':'')+'\">'+String(t).replace(/[<>]/g,'')+'</div>').join(''):'<div class=\"ok\">Engelsiz</div>';
    const votes=d.votes||[];
    el('votes').innerHTML=votes.length?votes.map(v=>'<div><b>'+String(v.name||'')+'</b> '+(v.direction||'')+' · '+String(v.note||'')+'</div>').join(''):'<div>oy yok</div>';
    drawLine('pc', s.price_curve||[], 'mid', '#3dff9a');
    drawLine('ec', s.equity_curve||[], 'equity', '#ffd166');
    const fills=s.recent_fills||[];
    el('fills').innerHTML=fills.length?fills.slice(0,12).map(t=>{const pnl=Number(t.pnl_usdt);return '<tr><td>'+String(t.timestamp||'').slice(11,19)+'</td><td>'+String(t.side||'').toUpperCase()+'</td><td>'+num(t.quantity,5)+'</td><td>'+num(t.price,2)+'</td><td class=\"'+(pnl>=0?'pos':'neg')+'\">'+num(pnl,3)+'</td><td>'+num(t.fee_usdt,4)+'</td></tr>';}).join(''):'<tr><td colspan=\"6\" class=\"lbl\">Henüz işlem yok — skor≥eşik + edge gerekir</td></tr>';
  }catch(e){console.warn(e)}
}
setInterval(tick,900);tick();
</script>
</body>
</html>
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
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
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Nexora Quant", version="0.2.0", lifespan=lifespan)


def _is_private_lan(host: str) -> bool:
    """Allow home/office Wi-Fi so phone can open dashboard on same network."""
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
    return state.snapshot()


@app.get("/portfolio")
def portfolio() -> dict:
    mark = state.latest_book.bid if state.latest_book else None
    return state.executor.snapshot(mark) if state.executor else {"status": "not_started"}
