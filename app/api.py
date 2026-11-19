"""Local dashboard + status API. Do not expose publicly without auth."""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
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
.footer{margin-top:12px;color:var(--m);font-size:11px;text-align:center}
@media(max-width:900px){
  .stats{grid-template-columns:repeat(3,1fr)}
  .row{grid-template-columns:1fr}
  .hero-pnl .amt{font-size:26px}
}
canvas{height:168px!important}
.card{transition:border-color .18s ease,transform .18s ease}
.card:hover{border-color:#2b5940;transform:translateY(-1px)}
.stat .v{letter-spacing:-.02em}
</style>
</head>
<body>
<main>
  <div class=\"top\">
    <div>
      <div class=\"brand\">NEXORA <span>QUANT</span></div>
      <div class=\"sub\">Spot L2 desk - fee-aware decision engine - paper / live</div>
      <div class=\"pills\" id=\"pills\"></div>
    </div>
    <div class=\"hero-pnl\">
      <div class=\"lbl\">Equity</div>
      <div class=\"amt\" id=\"eq\">???</div>
      <div class=\"sub\" id=\"eqsub\">realized / fees</div>
    </div>
  </div>

  <div class=\"stats\">
    <div class=\"stat\"><div class=\"l\">Sembol</div><div class=\"v\" id=\"sym\">???</div></div>
    <div class=\"stat\"><div class=\"l\">Skor / Esik</div><div class=\"v\" id=\"sc\">???</div></div>
    <div class=\"stat\"><div class=\"l\">Net PnL</div><div class=\"v\" id=\"net\">???</div></div>
    <div class=\"stat\"><div class=\"l\">Session PnL</div><div class=\"v\" id=\"sessionpnl\">???</div></div>
    <div class=\"stat\"><div class=\"l\">Islem</div><div class=\"v\" id=\"tc\">0</div></div>
    <div class=\"stat\"><div class=\"l\">Win rate (rolling)</div><div class=\"v\" id=\"wr\">???</div></div>
    <div class=\"stat\"><div class=\"l\">Drawdown</div><div class=\"v\" id=\"dd\">???</div></div>
  </div>

  <div class=\"row\">
    <div class=\"card\">
      <h2>Sinyal skoru</h2>
      <div class=\"gauge-wrap\"><div class=\"gauge\" id=\"g\"><span id=\"gval\">0.00</span></div></div>
      <canvas class=\"spark\" id=\"spark\" width=\"400\" height=\"36\"></canvas>
      <div class=\"meta\">
        <div><div class=\"l\">Rejim</div><div class=\"v\" id=\"reg\">???</div></div>
        <div><div class=\"l\">Karar</div><div class=\"v\" id=\"dec\">???</div></div>
        <div><div class=\"l\">Fiyat</div><div class=\"v\" id=\"px\">???</div></div>
        <div><div class=\"l\">Spread</div><div class=\"v\" id=\"spr\">???</div></div>
      </div>
    </div>
    <div class=\"card\">
      <h2>Neden islem var / yok</h2>
      <div class=\"why\" id=\"why\"><div class=\"lbl\">Veri bekleniyor</div></div>
      <h2 style=\"margin-top:12px\">Motor oylari</h2>
      <div class=\"why\" id=\"votes\"></div>
    </div>
    <div class=\"card\">
      <h2>Fiyat (son tickler)</h2>
      <canvas id=\"pc\" width=\"420\" height=\"120\"></canvas>
      <h2 style=\"margin-top:10px\">Equity egrisi</h2>
      <canvas id=\"ec\" width=\"420\" height=\"120\"></canvas>
    </div>
  </div>

  <div class=\"row\" style=\"margin-top:10px;grid-template-columns:1.4fr 1fr\">
    <div class=\"card\">
      <h2>Son islemler</h2>
      <div style=\"overflow:auto\">
        <table>
          <thead><tr><th>Saat</th><th>Yon</th><th>Miktar</th><th>Fiyat</th><th>PnL</th><th>Fee</th></tr></thead>
          <tbody id=\"fills\"></tbody>
        </table>
      </div>
    </div>
    <div class=\"card\">
      <h2>Canli log</h2>
      <div class=\"log\" id=\"log\"></div>
    </div>
  </div>
  <div class="row" style="margin-top:10px;grid-template-columns:1.1fr 1fr">
    <div class="card">
      <h2>Portfoy ve risk detayi</h2>
      <div class="meta">
        <div><div class="l">Serbest nakit</div><div class="v" id="cash">---</div></div>
        <div><div class="l">Acik pozisyon</div><div class="v" id="position">---</div></div>
        <div><div class="l">Ortalama giris</div><div class="v" id="entry">---</div></div>
        <div><div class="l">Acik PnL</div><div class="v" id="unreal">---</div></div>
        <div><div class="l">Gunluk fee</div><div class="v" id="dailyfee">---</div></div>
        <div><div class="l">Fee-net expectancy</div><div class="v" id="expect">---</div></div>
        <div><div class="l">Maker fill</div><div class="v" id="makerfill">---</div></div>
        <div><div class="l">Maker timeout</div><div class="v" id="makertimeout">---</div></div>
        <div><div class="l">Trades / hour</div><div class="v" id="tradeshour">---</div></div>
        <div><div class="l">Max DD</div><div class="v" id="maxdd">---</div></div>
        <div><div class="l">Events</div><div class="v" id="events">---</div></div>
      </div>
    </div>
    <div class="card">
      <h2>Ogrenme ve adaptasyon</h2>
      <div class="meta">
        <div><div class="l">Politika</div><div class="v" id="lm">---</div></div>
        <div><div class="l">Omur boyu islem</div><div class="v" id="lt">---</div></div>
        <div><div class="l">Entry esigi</div><div class="v" id="le">---</div></div>
        <div><div class="l">Pozisyon carpan</div><div class="v" id="ls">---</div></div>
        <div><div class="l">TP / compound</div><div class="v" id="ltp">---</div></div>
        <div><div class="l">Ogrenme notu</div><div class="v" id="ln" style="font-size:11px">---</div></div>
      </div>
    </div>
  </div>
  <div class="card" style="margin-top:10px">
    <h2>Dokuz sembol derinlik taramasi</h2>
    <div style="overflow:auto">
      <table>
        <thead><tr><th>Sembol</th><th>Durum</th><th>Bid</th><th>Ask</th><th>Spread</th><th>Veri yasi</th></tr></thead>
        <tbody id="scan"><tr><td colspan="6">Veri bekleniyor</td></tr></tbody>
      </table>
    </div>
  </div>
  <div class=\"footer\">Edge olmadan islem yok; round-trip komisyon ve kayma hesaba katilir. Yatirim tavsiyesi degildir.</div>
</main>
<script>
const el=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>c==='&'?'&amp;':c==='<'?'&lt;':c==='>'?'&gt;':c==='\"'?'&quot;':'&#39;');
function num(x,d=2){if(x===null||x===undefined||x==='')return '---';const n=Number(x);return Number.isFinite(n)?n.toFixed(d):'---'}
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
  const pts=(arr||[]).map((p,i)=>({i,y:Number(p[key])})).filter(p=>Number.isFinite(p.y));
  if(pts.length<2){ctx.fillStyle='#7f9a8c';ctx.font='11px Segoe UI';ctx.fillText('Veri birikiyor',12,h/2);return}
  let mn=Math.min(...pts.map(p=>p.y)),mx=Math.max(...pts.map(p=>p.y));
  if(mx===mn){const pad=Math.max(Math.abs(mx)*0.0005,0.000001);mx+=pad;mn-=pad}
  const left=48,right=w-8,top=10,bottom=h-20;
  const x=i=>left+(i/Math.max(1,arr.length-1))*(right-left);
  const y=v=>bottom-((v-mn)/(mx-mn))*(bottom-top);
  ctx.font='10px Segoe UI';ctx.lineWidth=1;ctx.strokeStyle='#1a2f24';ctx.fillStyle='#7f9a8c';
  for(let k=0;k<=3;k++){const yy=top+(bottom-top)*k/3;ctx.beginPath();ctx.moveTo(left,yy);ctx.lineTo(right,yy);ctx.stroke();ctx.fillText((mx-(mx-mn)*k/3).toFixed(2),3,yy+3)}
  const grad=ctx.createLinearGradient(0,top,0,bottom);grad.addColorStop(0,color+'44');grad.addColorStop(1,color+'00');
  ctx.beginPath();pts.forEach((p,j)=>{const xx=x(p.i),yy=y(p.y);j?ctx.lineTo(xx,yy):ctx.moveTo(xx,yy)});
  ctx.lineTo(x(pts[pts.length-1].i),bottom);ctx.lineTo(x(pts[0].i),bottom);ctx.closePath();ctx.fillStyle=grad;ctx.fill();
  ctx.beginPath();pts.forEach((p,j)=>{const xx=x(p.i),yy=y(p.y);j?ctx.lineTo(xx,yy):ctx.moveTo(xx,yy)});
  ctx.strokeStyle=color;ctx.lineWidth=2;ctx.lineJoin='round';ctx.lineCap='round';ctx.stroke();
  const last=pts[pts.length-1];ctx.beginPath();ctx.arc(x(last.i),y(last.y),3,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();
  ctx.fillStyle='#cfe8d8';ctx.textAlign='right';ctx.fillText(last.y.toFixed(3),right,bottom-4);ctx.textAlign='left';
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
let updating=false;
async function tick(){
  if(updating)return;updating=true;
  try{
    const response=await fetch('/status',{cache:'no-store'});
    if(!response.ok)throw new Error('status '+response.status);
    const s=await response.json();
    const p=s.portfolio||{};
    const a=s.analysis||{};
    const d=s.last_decision||{};
    const eq=Number(p.equity_usdt||p.cash_usdt||0);
    const start=Number(p.starting_cash_usdt||100);
    const realized=Number(p.realized_pnl_usdt||0);
    const fees=Number(p.fees_paid_usdt||0);
    el('eq').textContent=num(eq,2)+' USDT';
    el('eq').className='amt'+(eq<start?' neg':'');
    const feeSchedule=s.fee_schedule||{};
    el('eqsub').textContent='realized '+num(realized,3)+' / fees '+num(fees,3)+' / taker '+num(Number(feeSchedule.taker_rate||0)*10000,2)+' bps';
    el('sym').textContent=String(s.symbol||'???').toUpperCase();
    const minSc=Number((s.risk_limits&&s.risk_limits.entry_min_score)||0.28);
    const score=Number(a.score!=null?a.score:0);
    el('sc').textContent=num(score,2)+' / '+num(minSc,2);
    el('net').textContent=num(realized,3);
    el('net').className='v'+(realized>=0?' pos':' neg');
    const sessionPnl=Number(s.session_realized_pnl_usdt||0);
    el('sessionpnl').textContent=(sessionPnl>=0?'+':'')+num(sessionPnl,3);
    el('sessionpnl').className='v'+(sessionPnl>=0?' pos':' neg');
    const fills=s.recent_fills||[];
    const expectancy=s.session_expectancy||{};
    el('wr').textContent=expectancy.n?num(100*Number(expectancy.win_rate||0),0)+'%':'???';
    el('tc').textContent=String(s.closed_trade_count??p.trade_count??0);
    el('dd').textContent=num(s.max_drawdown_pct,2)+'%';
    const pills=[];
    pills.push('<span class=\"pill '+(s.connected?'':'off')+'\">'+(s.connected?'L2 OK':'L2 KOPUK')+'</span>');
    pills.push('<span class=\"pill\">'+esc((s.mode||'paper').toUpperCase())+'</span>');
    const engineStatus=String(s.engine_task_status||'unknown').toUpperCase();
    pills.push('<span class=\"pill '+(engineStatus==='RUNNING'?'':'off')+'\">ENGINE '+esc(engineStatus)+'</span>');
    if(s.kill_switch)pills.push('<span class=\"pill off\">KILL</span>');
    if(s.emergency)pills.push('<span class=\"pill off\">EMERGENCY</span>');
    pills.push('<span class=\"pill\">data '+num(s.data_age_seconds,1)+'s</span>');
    pills.push('<span class=\"pill\">reconnect '+Number(s.reconnect_count||0)+'</span>');
    el('pills').innerHTML=pills.join('');
    setGauge(score,minSc);
    drawSpark(s.score_history||[]);
    el('reg').textContent=(a.regime||'???')+' / OBI '+num(a.weighted_obi,2);
    el('dec').textContent=(d.action||'???');
    const m=s.market||{};
    el('px').textContent=num((Number(m.bid)+Number(m.ask))/2,2);
    el('spr').textContent=num(a.spread_bps,3)+' bps';
    const blockers=d.blockers||[];
    const rat=d.rationale||[];
    const why=[...blockers.map(x=>'BLOCK: '+x),...rat.map(x=>'INFO: '+x)];
    el('why').innerHTML=why.length?why.slice(0,14).map(t=>'<div class=\"'+(String(t).startsWith('BLOCK')?'bad':'')+'\">'+esc(t)+'</div>').join(''):'<div class=\"ok\">No active blockers reported</div>';
    const votes=d.votes||[];
    el('votes').innerHTML=votes.length?votes.map(v=>'<div><b>'+String(esc(v.name||''))+'</b> '+(esc(v.direction||''))+' / '+String(esc(v.note||''))+'</div>').join(''):'<div class=\"lbl\">oy yok</div>';
    drawLine('pc',s.price_curve||[],'mid','#2eff9a');
    drawLine('ec',s.equity_curve||[],'equity','#ffc14d');
    el('fills').innerHTML=fills.length?fills.slice(0,14).map(t=>{const pnl=Number(t.pnl_usdt);return '<tr><td>'+esc(String(t.timestamp||'').slice(11,19))+'</td><td>'+esc(String(t.side||'').toUpperCase())+'</td><td>'+num(t.quantity,5)+'</td><td>'+num(t.price,2)+'</td><td class=\"'+(pnl>=0?'pos':'neg')+'\">'+num(pnl,3)+'</td><td>'+num(t.fee_usdt,4)+'</td></tr>';}).join(''):'<tr><td colspan=\"6\" style=\"color:#7f9a8c\">Henuz fill yok</td></tr>';
    const scan=s.scan_board||[];
    el('scan').innerHTML=scan.length?scan.map(x=>{
      const ok=x.status==='synchronized';
      const status=String(x.status||'awaiting').toUpperCase();
      return '<tr><td>'+esc(String(x.symbol||'').toUpperCase())+'</td><td class="'+(ok?'pos':'neg')+'">'+status+'</td><td>'+num(x.bid,6)+'</td><td>'+num(x.ask,6)+'</td><td>'+num(x.spread_bps,2)+' bps</td><td>'+num(x.data_age_seconds,2)+'s</td></tr>';
    }).join(''):'<tr><td colspan="6">Watchlist bos</td></tr>';
    const logs=s.live_log||[];
    el('log').innerHTML=logs.length?logs.slice(0,30).map(x=>'<div>'+esc(x)+'</div>').join(''):'<div>Log bos</div>';
    const L=s.learner_snapshot||{};
    const qty=Number(p.base_quantity||0);
    el('cash').textContent=num(p.cash_usdt,2)+' USDT';
    el('position').textContent=qty>0?num(qty,6)+' '+String(s.symbol||'').replace(/usdt$/i,'').toUpperCase():'FLAT';
    el('entry').textContent=qty>0?num(p.average_entry_price,2):'--';
    el('unreal').textContent=num(p.unrealized_pnl_usdt,3)+' USDT';
    el('unreal').className='v'+(Number(p.unrealized_pnl_usdt||0)>=0?' pos':' neg');
    el('dailyfee').textContent=num(s.session_fees_usdt,3)+' USDT';
    el('expect').textContent=expectancy.n?num(expectancy.expectancy_usdt,4)+' / trade ('+expectancy.n+')':'sample < 50';
    const maker=s.maker_stats||{};
    el('makerfill').textContent=maker.fill_rate==null?'N/A':num(100*maker.fill_rate,1)+'%';
    el('makertimeout').textContent=maker.timeout_rate==null?'N/A':num(100*maker.timeout_rate,1)+'%';
    el('tradeshour').textContent=String(s.trades_per_hour??0);
    el('maxdd').textContent=num(s.max_drawdown_pct_observed,2)+'%';
    el('events').textContent=String(s.events_seen??0);
    el('lm').textContent=(L.growth_mode||'rebuild')+(L.frozen?' / FROZEN':' / ADAPTIVE');
    el('lt').textContent=String(L.lifetime_trades??L.trades??0);
    el('le').textContent=num(L.entry_min_score,3);
    el('ls').textContent=num(L.size_bias,2)+'x';
    el('ltp').textContent=num(L.tp_scale,2)+' / '+num(L.compound_fraction,2);
    el('ln').textContent=L.note||'No learner update yet';
  }catch(e){console.warn(e);el('pills').innerHTML='<span class=\"pill off\">DASHBOARD DATA ERROR</span>'}finally{updating=false}
}
setInterval(tick,1200);tick();
</script>
</body>
</html>
"""


_engine_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine_task
    task = asyncio.create_task(run(), name="nexora-engine")
    _engine_task = task

    def _done(t: asyncio.Task) -> None:
        try:
            exc = t.exception()
        except asyncio.CancelledError:
            return
        if exc:
            import logging
            logging.getLogger(__name__).error(
                "Engine task crashed: %s",
                exc,
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    task.add_done_callback(_done)
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        _engine_task = None


app = FastAPI(title="Nexora Quant", version="0.2.0", lifespan=lifespan)


def _is_private_lan(host: str) -> bool:
    """Return True only for RFC1918 IPv4 or unique-local IPv6 client addresses."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv4Address):
        return address in ipaddress.ip_network("10.0.0.0/8") or any(
            address in ipaddress.ip_network(network)
            for network in ("172.16.0.0/12", "192.168.0.0/16")
        )
    return address in ipaddress.ip_network("fc00::/7")


@app.middleware("http")
async def restrict_remote_access(request: Request, call_next):
    client_host = request.client.host if request.client else ""
    if client_host in {"127.0.0.1", "::1", "localhost", "testclient"}:
        return await call_next(request)
    # LAN access is an explicit opt-in. Otherwise every non-loopback client,
    # including a phone on home Wi-Fi, must present the bearer token.
    allow_lan = os.getenv("NEXORA_ALLOW_LAN", "").strip().lower() in {"1", "true", "yes", "on"}
    if allow_lan and _is_private_lan(client_host):
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


def _engine_task_status() -> str:
    task = _engine_task
    if task is None:
        return "not_started"
    if not task.done():
        return "running"
    if task.cancelled():
        return "stopped"
    try:
        return "failed" if task.exception() is not None else "stopped"
    except asyncio.CancelledError:
        return "stopped"


@app.get("/health")
def health() -> dict:
    from app.config import settings as _s

    engine_status = _engine_task_status()
    snapshot = state.snapshot()
    market_connected = bool(snapshot.get("connected"))
    safety_halted = bool(snapshot.get("kill_switch") or snapshot.get("emergency"))
    if engine_status == "running" and market_connected and not safety_halted:
        overall = "ok"
    elif engine_status == "running":
        overall = "degraded"
    elif engine_status == "failed":
        overall = "error"
    else:
        overall = "not_ready"
    return {
        "status": overall,
        "mode": getattr(_s, "trading_mode", "paper"),
        "engine": engine_status,
        "market_data_connected": market_connected,
        "data_age_seconds": snapshot.get("data_age_seconds"),
        "kill_switch": snapshot.get("kill_switch", False),
        "emergency": snapshot.get("emergency", False),
        "last_error": snapshot.get("last_error"),
    }


@app.get("/status")
def status() -> dict:
    from datetime import datetime, timezone
    from app.config import settings as _s
    from app.fees import schedule_from_settings

    snapshot = state.snapshot()
    snapshot["engine_task_status"] = _engine_task_status()
    snapshot["server_time"] = datetime.now(timezone.utc).isoformat()
    snapshot["fee_schedule"] = schedule_from_settings(
        fee_rate=_s.fee_rate,
        vip_level=_s.fee_vip_level,
        use_bnb_discount=_s.fee_use_bnb_discount,
    ).to_dict()
    snapshot["fee_schedule"]["assumption"] = (
        "configured BNB discount; verify BNB balance and account eligibility"
        if _s.fee_use_bnb_discount else "conservative configured fee; no BNB discount assumed"
    )
    return snapshot


@app.get("/portfolio")
def portfolio() -> dict:
    mark = state.latest_book.bid if state.latest_book else None
    return state.executor.snapshot(mark) if state.executor else {"status": "not_started"}
