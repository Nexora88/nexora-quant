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
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\"/>
<title>Nexora Quant Desk</title>
<style>
:root{
  --bg:#050a08;--panel:#0b1410;--card:#0e1a14;--line:#1a2f24;
  --g:#2eff9a;--g2:#12c96a;--r:#ff4d6a;--a:#ffc14d;--m:#7f9a8c;--t:#e7f7ee;
  --glow:0 0 28px #2eff9a33;
}
*{box-sizing:border-box}
body{margin:0;background:
  radial-gradient(1000px 480px at 8% -15%,#0d3a2855,transparent),
  radial-gradient(800px 400px at 100% 0%,#1a203055,transparent),
  var(--bg);color:var(--t);font:13.5px/1.45 \"Segoe UI\",system-ui,sans-serif}
main{max-width:1280px;margin:0 auto;padding:14px 12px 48px}
.top{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-start;justify-content:space-between;margin-bottom:12px}
.brand{font-size:20px;font-weight:800;letter-spacing:.06em}
.brand span{color:var(--g);text-shadow:var(--glow)}
.sub{color:var(--m);font-size:11px;margin-top:3px}
.hero-pnl{text-align:right}
.hero-pnl .lbl{color:var(--m);font-size:10px;letter-spacing:.1em;text-transform:uppercase}
.hero-pnl .amt{font-size:34px;font-weight:800;font-variant-numeric:tabular-nums;color:var(--g);text-shadow:var(--glow)}
.hero-pnl .amt.neg{color:var(--r);text-shadow:0 0 20px #ff4d6a44}
.pills{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.pill{border:1px solid var(--line);background:#0c1812;color:var(--g);padding:4px 10px;border-radius:999px;font-size:10px;font-weight:700}
.pill.off{color:var(--r);border-color:#4a2030;background:#1a0c10}
.pill.warn{color:var(--a);border-color:#4a3a10}
.stats{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-bottom:10px}
.stat{background:linear-gradient(160deg,#122019,#0a110e);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.stat .l{color:var(--m);font-size:10px;text-transform:uppercase;letter-spacing:.08em}
.stat .v{font-size:18px;font-weight:750;margin-top:4px;font-variant-numeric:tabular-nums}
.row{display:grid;grid-template-columns:1.05fr 1.2fr 1fr;gap:10px}
.card{background:linear-gradient(165deg,#121c17,#0b120e);border:1px solid var(--line);border-radius:14px;padding:12px 14px;min-height:0}
h2{margin:0 0 10px;font-size:12px;color:#cfe8d8;letter-spacing:.04em;text-transform:uppercase}
.gauge-wrap{display:flex;align-items:center;justify-content:center;padding:8px 0}
.gauge{width:150px;height:150px;border-radius:50%;display:grid;place-items:center;position:relative;box-shadow:var(--glow)}
.gauge::after{content:\"\";position:absolute;inset:14px;border-radius:50%;background:#070e0b;border:1px solid #1a2a20}
.gauge span{position:relative;z-index:1;font-size:28px;font-weight:800}
.meta{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}
.meta div{background:#0a120e;border:1px solid var(--line);border-radius:10px;padding:8px}
.meta .l{color:var(--m);font-size:10px}.meta .v{font-weight:700;margin-top:2px}
canvas{width:100%!important;height:120px!important;background:#070e0b;border-radius:10px;border:1px solid var(--line)}
.why{max-height:160px;overflow:auto;font-size:12px}
.why div{padding:4px 0;border-bottom:1px solid #152018}
.why .bad{color:var(--r)}.why .ok{color:var(--g)}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:6px 4px;border-bottom:1px solid #152018;text-align:left;font-variant-numeric:tabular-nums}
th{color:var(--m);font-weight:600;font-size:10px;text-transform:uppercase}
.pos{color:var(--g)}.neg{color:var(--r)}
.log{font-family:ui-monospace,Consolas,monospace;font-size:11px;max-height:140px;overflow:auto;background:#070e0b;border:1px solid var(--line);border-radius:10px;padding:8px;color:#9bbfad}
.log div{padding:2px 0}
.spark{height:36px;width:100%}
.coin{display:inline-flex;align-items:center;gap:6px}
.coin-logo{width:16px;height:16px;border-radius:50%}
.uni-row{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #152018}
.uni-row .sc{color:var(--g);font-weight:700}
.footer{margin-top:12px;color:var(--m);font-size:11px;text-align:center}
@media(max-width:900px){
  .stats{grid-template-columns:repeat(3,1fr)}
  .row{grid-template-columns:1fr}
  .hero-pnl .amt{font-size:26px}
}
</style>
</head>
<body>
<main>
  <div class=\"top\">
    <div>
      <div class=\"brand\">NEXORA <span>QUANT</span></div>
      <div class=\"sub\">Spot L2 desk · fee-aware edge · paper / live</div>
      <div class=\"pills\" id=\"pills\"></div>
    </div>
    <div class=\"hero-pnl\">
      <div class=\"lbl\">Equity</div>
      <div class=\"amt\" id=\"eq\">—</div>
      <div class=\"sub\" id=\"eqsub\">realized · fees</div>
    </div>
  </div>

  <div class=\"stats\">
    <div class=\"stat\"><div class=\"l\">Sembol</div><div class=\"v\" id=\"sym\">—</div></div>
    <div class=\"stat\"><div class=\"l\">Skor / Eşik</div><div class=\"v\" id=\"sc\">—</div></div>
    <div class=\"stat\"><div class=\"l\">Net PnL</div><div class=\"v\" id=\"net\">—</div></div>
    <div class=\"stat\"><div class=\"l\">İşlem</div><div class=\"v\" id=\"tc\">0</div></div>
    <div class=\"stat\"><div class=\"l\">Win rate</div><div class=\"v\" id=\"wr\">—</div></div>
    <div class=\"stat\"><div class=\"l\">Drawdown</div><div class=\"v\" id=\"dd\">—</div></div>
  </div>

  <div class=\"stats\" style=\"grid-template-columns:repeat(6,1fr);margin-top:-2px\">
    <div class=\"stat\"><div class=\"l\">Saatlik işlem</div><div class=\"v\" id=\"tph\">—</div></div>
    <div class=\"stat\"><div class=\"l\">Günlük fee</div><div class=\"v\" id=\"dfee\">—</div></div>
    <div class=\"stat\"><div class=\"l\">Kapanan</div><div class=\"v\" id=\"closedn\">—</div></div>
    <div class=\"stat\"><div class=\"l\">Session PnL</div><div class=\"v\" id=\"spnl\">—</div></div>
    <div class=\"stat\"><div class=\"l\">Son çıkış</div><div class=\"v\" id=\"lexit\">—</div></div>
    <div class=\"stat\"><div class=\"l\">Pozisyon</div><div class=\"v\" id=\"mhold\">—</div></div>
  </div>

  <div class=\"row\">
    <div class=\"card\">
      <h2>Sinyal skometresi</h2>
      <div class=\"gauge-wrap\"><div class=\"gauge\" id=\"g\"><span id=\"gval\">0.00</span></div></div>
      <canvas class=\"spark\" id=\"spark\" width=\"400\" height=\"36\"></canvas>
      <div class=\"meta\">
        <div><div class=\"l\">Rejim</div><div class=\"v\" id=\"reg\">—</div></div>
        <div><div class=\"l\">Karar</div><div class=\"v\" id=\"dec\">—</div></div>
        <div><div class=\"l\">Fiyat</div><div class=\"v\" id=\"px\">—</div></div>
        <div><div class=\"l\">Spread</div><div class=\"v\" id=\"spr\">—</div></div>
      </div>
    </div>
    <div class=\"card\">
      <h2>Neden işlem var / yok</h2>
      <div class=\"why\" id=\"why\"><div class=\"lbl\">bekleniyor…</div></div>
      <h2 style=\"margin-top:12px\">Throttle / blockers</h2>
      <div class=\"why\" id=\"blk\"></div>
      <h2 style=\"margin-top:12px\">Motor oyları</h2>
      <div class=\"why\" id=\"votes\"></div>
    </div>
    <div class=\"card\">
      <h2>Fiyat (son tickler)</h2>
      <canvas id=\"pc\" width=\"420\" height=\"120\"></canvas>
      <h2 style=\"margin-top:10px\">Equity eğrisi</h2>
      <canvas id=\"ec\" width=\"420\" height=\"120\"></canvas>
    </div>
  </div>

  <div class=\"row\" style=\"margin-top:10px;grid-template-columns:1.4fr 1fr\">
    <div class=\"card\">
      <h2>Son işlemler</h2>
      <div style=\"overflow:auto\">
        <table>
          <thead><tr><th>Saat</th><th>Coin</th><th>Yön</th><th>Miktar</th><th>Fiyat</th><th>PnL</th><th>Fee</th></tr></thead>
          <tbody id=\"fills\"></tbody>
        </table>
      </div>
    </div>
    <div class=\"card\">
      <h2>Canlı log</h2>
      <div class=\"log\" id=\"log\"></div>
      <h2 style=\"margin-top:10px\">Öğrenen</h2>
      <div class=\"meta\">
        <div><div class=\"l\">Mod</div><div class=\"v\" id=\"lm\">—</div></div>
        <div><div class=\"l\">Not</div><div class=\"v\" id=\"ln\" style=\"font-size:11px\">—</div></div>
      </div>
      <h2 style=\"margin-top:10px\">Universe</h2>
      <div class=\"why\" id=\"uni\"></div>
      <div class=\"sub\" style=\"margin-top:6px\">Aktif: <span id=\"act\">—</span></div>
    </div>
  </div>
  <div class=\"footer\">Ölçülen edge olmadan kâr yok · fee round-trip · investment advice değil</div>
</main>
<script>
const el=id=>document.getElementById(id);
function num(x,d=2){const n=Number(x);return Number.isFinite(n)?n.toFixed(d):'—'}
function setGauge(score,minScore){
  const s=Math.max(0,Math.min(1,Number(score)||0));
  const hot=s>=(Number(minScore)||0.28);
  const deg=Math.round(s*360);
  const c=hot?'#2eff9a':(s>=0.2?'#ffc14d':'#ff4d6a');
  el('g').style.background=`conic-gradient(${c} ${deg}deg,#152019 0)`;
  el('gval').textContent=num(score,2);
  el('gval').style.color=c;
}
function drawLine(id,arr,key,color){
  const c=el(id);if(!c)return;const ctx=c.getContext('2d');
  const w=c.width,h=c.height;ctx.clearRect(0,0,w,h);
  if(!arr||arr.length<2){ctx.fillStyle='#7f9a8c';ctx.fillText('veri yok',12,h/2);return}
  const ys=arr.map(p=>Number(p[key])).filter(Number.isFinite);
  if(ys.length<2)return;
  let mn=Math.min(...ys),mx=Math.max(...ys);if(mx===mn){mx+=1e-9;mn-=1e-9}
  ctx.strokeStyle=color;ctx.lineWidth=1.6;ctx.beginPath();
  arr.forEach((p,i)=>{const y=Number(p[key]);if(!Number.isFinite(y))return;
    const x=i/(arr.length-1)*(w-8)+4;const yy=h-8-((y-mn)/(mx-mn))*(h-16);
    i?ctx.lineTo(x,yy):ctx.moveTo(x,yy)});ctx.stroke();
}
function drawSpark(arr){
  const c=el('spark');if(!c)return;const ctx=c.getContext('2d');
  const w=c.width,h=c.height;ctx.clearRect(0,0,w,h);
  if(!arr||arr.length<2)return;
  const ys=arr.map(p=>Number(p.score)).filter(Number.isFinite);
  let mn=0,mx=1;
  ctx.strokeStyle='#2eff9a';ctx.lineWidth=1.4;ctx.beginPath();
  ys.forEach((y,i)=>{const x=i/(ys.length-1)*(w-4)+2;const yy=h-4-((y-mn)/(mx-mn))*(h-8);
    i?ctx.lineTo(x,yy):ctx.moveTo(x,yy)});ctx.stroke();
}
function coinLogo(sym){const b=String(sym||'').toLowerCase().replace('usdt','').replace('busd','');return 'https://cryptoicons.org/api/icon/'+b+'/32';}
function coinCell(sym){const s=String(sym||'—').toUpperCase();return '<span class=\"coin\"><img class=\"coin-logo\" src=\"'+coinLogo(sym)+'\" onerror=\"this.style.display=\'none\'\" alt=\"\"/>'+s+'</span>';}
async function tick(){
  try{
    const s=await(await fetch('/status')).json();
    const p=s.portfolio||{};
    const a=s.analysis||{};
    const d=s.last_decision||{};
    const eq=Number(p.equity_usdt||p.cash_usdt||0);
    const start=Number(p.starting_cash_usdt||100);
    const realized=Number(p.realized_pnl_usdt||0);
    const fees=Number(p.fees_paid_usdt||0);
    const trades=Number(p.trade_count||0);
    el('eq').textContent=num(eq,2)+' USDT';
    el('eq').className='amt'+(eq<start?' neg':'');
    el('eqsub').textContent='realized '+num(realized,3)+' · fees '+num(fees,3);
    el('sym').textContent=String(s.symbol||'—').toUpperCase();
    const minSc=Number((s.risk_limits&&s.risk_limits.entry_min_score)||0.28);
    const score=Number(a.score!=null?a.score:0);
    el('sc').textContent=num(score,2)+' / '+num(minSc,2);
    el('net').textContent=num(realized,3);
    el('net').className='v'+(realized>=0?' pos':' neg');
    el('tc').textContent=String(trades);
    const fills=s.recent_fills||[];
    const closed=fills.filter(t=>t.pnl_usdt!=null);
    const wins=closed.filter(t=>Number(t.pnl_usdt)>0).length;
    el('wr').textContent=closed.length?(num(100*wins/closed.length,0)+'%'):'—';
    const peak=Number(s.peak_equity||eq)||eq;
    const dd=peak>0?((peak-eq)/peak*100):0;
    el('dd').textContent=num(dd,2)+'%';
    const pills=[];
    pills.push('<span class=\"pill \"'+(s.connected?'':'off')+'\">'+(s.connected?'LIVE L2':'L2 KOPUK')+'</span>');
    pills.push('<span class=\"pill\">'+(s.mode||'paper').toUpperCase()+'</span>');
    if(s.kill_switch)pills.push('<span class=\"pill off\">KILL</span>');
    if(s.emergency)pills.push('<span class=\"pill off\">EMERGENCY</span>');
    pills.push('<span class=\"pill\">events '+(s.events_seen||0)+'</span>');
    el('pills').innerHTML=pills.join('');
    setGauge(score,minSc);
    drawSpark(s.score_history||[]);
    el('reg').textContent=(a.regime||'—')+' · OBI '+num(a.weighted_obi,2);
    el('dec').textContent=(d.action||'—');
    const m=s.market||{};
    el('px').textContent=num((Number(m.bid)+Number(m.ask))/2,2);
    el('spr').textContent=num(a.spread_bps,3)+' bps';
    const blockers=d.blockers||[];
    const rat=d.rationale||[];
    const why=[...blockers.map(x=>'⛔ '+x),...rat.map(x=>'· '+x)];
    el('why').innerHTML=why.length?why.slice(0,14).map(t=>'<div class=\"'+(String(t).includes('⛔')?'bad':'')+'\">'+String(t).replace(/[<>]/g,'')+'</div>').join(''):'<div class=\"ok\">Engelsiz — edge + flow bekleniyor olabilir</div>';
    const votes=d.votes||[];
    el('votes').innerHTML=votes.length?votes.map(v=>'<div><b>'+String(v.name||'')+'</b> '+(v.direction||'')+' · '+String(v.note||'')+'</div>').join(''):'<div class=\"lbl\">oy yok</div>';
    drawLine('pc',s.price_curve||[],'mid','#2eff9a');
    drawLine('ec',s.equity_curve||[],'equity','#ffc14d');
    el('fills').innerHTML=fills.length?fills.slice(0,16).map(t=>{const pnl=Number(t.pnl_usdt);const side=String(t.side||'').toUpperCase();const sideCls=side==='BUY'||side==='LONG'?'pos':'neg';return '<tr><td>'+String(t.timestamp||'').slice(11,19)+'</td><td>'+coinCell(t.symbol||s.symbol)+'</td><td class=\"'+sideCls+'\"><b>'+side+'</b></td><td>'+num(t.quantity,5)+'</td><td>'+num(t.price,2)+'</td><td class=\"'+(pnl>=0?'pos':'neg')+'\">'+num(pnl,3)+'</td><td>'+num(t.fee_usdt,4)+'</td></tr>';}).join(''):'<tr><td colspan=\"7\" style=\"color:#7f9a8c\">Henüz fill yok — edge + hold + fee kapısı bekleniyor</td></tr>';
    const logs=s.live_log||[];
    el('log').innerHTML=logs.length?logs.slice(0,30).map(x=>'<div>'+String(x).replace(/[<>]/g,'')+'</div>').join(''):'<div>log boş</div>';
    const L=s.learner_snapshot||{};
    el('lm').textContent=L.growth_mode||'—';
    el('ln').textContent=L.note||'—';
    const uni=s.universe_board||s.router_board||[];
    el('uni').innerHTML=uni.length?uni.slice(0,8).map(u=>'<div class=\"uni-row\"><span class=\"coin\"><img class=\"coin-logo\" src=\"'+coinLogo(u.symbol)+'\" onerror=\"this.style.display=\'none\'\"/>'+String(u.symbol||'').toUpperCase()+'</span><span class=\"sc\">'+(u.rank_score!=null?num(u.rank_score,3):num(u.score,2))+'</span></div>').join(''):'<div class=\"lbl\">universe taranıyor…</div>';
    el('tph').textContent=String(s.hourly_trade_count!=null?s.hourly_trade_count:'—');
    el('dfee').textContent=num(s.session_fees_usdt,3)+' USDT';
    el('closedn').textContent=String(s.closed_trade_count!=null?s.closed_trade_count:'—');
    const sp=Number(s.session_realized_pnl_usdt||0);
    if(el('spnl')){el('spnl').textContent=num(sp,3)+' USDT';el('spnl').className='v '+(sp>=0?'pos':'neg');}
    if(el('lexit'))el('lexit').textContent=String(s.last_exit_reason||'—').slice(0,28);
    el('mhold').textContent=(s.position_opened_at?('açık ' + Math.round((Date.now()/1000-Number(s.position_opened_at)))+'s'):'flat');
    el('act').textContent=String(s.trade_symbol||s.symbol||'—').toUpperCase();
    const bl=s.blockers_live||[];
    el('blk').innerHTML=bl.length?bl.slice(0,8).map(x=>'<div class=\"bad\">⛔ '+String(x).replace(/[<>]/g,'')+'</div>').join(''):'<div class=\"ok\">Throttle temiz</div>';
  }catch(e){console.warn(e)}
}
setInterval(tick,900);tick();
</script>
</body>
</html>
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tests / CI must not open Binance L2 sockets.
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


app = FastAPI(title="Nexora Quant", version="0.3.0", lifespan=lifespan)


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
