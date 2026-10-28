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
<html lang=\"tr\"><head>
<meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>Nexora Quant · Live Desk</title>
<style>
:root{--bg:#050a08;--g:#39ff98;--r:#ff5c6c;--a:#ffd166;--m:#8eab98;--l:#1a2e24}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(1000px 500px at 10% -10%,#0d2a1c,transparent),var(--bg);color:#e8f6ee;font:14px/1.4 system-ui,sans-serif}
main{max-width:1220px;margin:auto;padding:18px 14px 40px}
.top{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center}
.brand{font-weight:800;letter-spacing:.06em;font-size:22px}.brand b{color:var(--g)}
.pnlbig{font-size:34px;font-weight:800;font-variant-numeric:tabular-nums;color:var(--g);text-shadow:0 0 18px #39ff9866}
.pills{display:flex;gap:8px;flex-wrap:wrap}.pill{padding:6px 11px;border-radius:999px;border:1px solid #2a5a40;background:#0f2419;color:var(--g);font-size:11px;font-weight:700}
.pill.bad{border-color:#6a2830;background:#240e12;color:var(--r)}.pill.warn{border-color:#6a4a18;background:#241a08;color:var(--a)}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:14px}
.card{background:linear-gradient(160deg,#121c17,#0b110e);border:1px solid var(--l);border-radius:14px;padding:14px}
.lbl{color:var(--m);font-size:11px;text-transform:uppercase;letter-spacing:.08em}
.val{font-size:22px;font-weight:750;margin-top:6px;font-variant-numeric:tabular-nums}
.row2{display:grid;grid-template-columns:1fr 1.2fr 1fr;gap:10px;margin-top:10px}
h2{margin:0 0 10px;font-size:13px}
.gauge-wrap{position:relative;height:140px;display:flex;align-items:center;justify-content:center}
.gauge{width:160px;height:160px;border-radius:50%;display:grid;place-items:center;position:relative}
.gauge::after{content:\"\";position:absolute;inset:14px;border-radius:50%;background:#0a100e}
.gauge span{position:relative;z-index:1;font-size:28px;font-weight:800;font-variant-numeric:tabular-nums}
.flash{animation:flash 0.8s ease 2}@keyframes flash{0%,100%{box-shadow:0 0 0 transparent}50%{box-shadow:0 0 28px #39ff98aa}}
.log{font-family:ui-monospace,Consolas,monospace;font-size:12px;max-height:220px;overflow:auto;background:#070c0a;border-radius:10px;padding:10px;border:1px solid var(--l)}
.log div{padding:6px 0;border-bottom:1px solid #152019;color:#b7d0c2}
.log .hi{color:var(--g)}.log .bad{color:var(--r)}
.bar{height:10px;background:#152019;border-radius:6px;overflow:hidden;margin-top:8px}.bar>i{display:block;height:100%;background:linear-gradient(90deg,#1a6b45,var(--g))}
.table{width:100%;border-collapse:collapse;font-size:12px}.table td,.table th{padding:6px 4px;border-bottom:1px solid #152019;text-align:left}
.pos{color:var(--g)}.neg{color:var(--r)}
.foot{margin-top:18px;color:#6d8578;font-size:12px;line-height:1.55}
@media(max-width:900px){.grid,.row2{grid-template-columns:1fr 1fr}}
@media(max-width:520px){.grid,.row2{grid-template-columns:1fr}}
</style></head><body><main>
<div class=\"top\">
  <div><div class=\"brand\">NEXORA <b>QUANT</b></div>
  <div class=\"lbl\" style=\"margin-top:4px\">ATR risk · spoof ≥1.5s · BTC kilit · order-flow</div></div>
  <div class=\"pnlbig\" id=\"pnlCounter\">$0.00</div>
  <div class=\"pills\">
    <span class=\"pill\" id=\"modePill\">—</span>
    <span class=\"pill\" id=\"symPill\">—</span>
    <span class=\"pill\" id=\"btcPill\">BTC</span>
    <span class=\"pill\" id=\"spoofPill\">SPOOF</span>
    <span class=\"pill\" id=\"goalPill\">GOAL</span>
  </div>
</div>
<div class=\"grid\">
  <div class=\"card\"><div class=\"lbl\">Equity</div><div class=\"val\" id=\"equity\">—</div><div class=\"lbl\" id=\"realized\">—</div></div>
  <div class=\"card\"><div class=\"lbl\">Unrealized</div><div class=\"val\" id=\"upnl\">—</div><div class=\"lbl\" id=\"cash\">—</div></div>
  <div class=\"card\"><div class=\"lbl\">Dinamik TP / SL</div><div class=\"val\" id=\"tpsl\">—</div><div class=\"lbl\" id=\"atrNote\">—</div></div>
  <div class=\"card\"><div class=\"lbl\">Flow / Regime</div><div class=\"val\" id=\"flow\">—</div><div class=\"lbl\" id=\"regime\">—</div></div>
</div>
<div class=\"row2\">
  <div class=\"card\" id=\"gaugeCard\">
    <h2>Sinyal skometresi</h2>
    <div class=\"gauge-wrap\"><div class=\"gauge\" id=\"gauge\"><span id=\"scoreVal\">0.00</span></div></div>
    <div class=\"bar\"><i id=\"scoreBar\" style=\"width:0%\"></i></div>
    <div class=\"lbl\" style=\"margin-top:8px\" id=\"flashMsg\">score ≥ 0.65 → TRADE band</div>
  </div>
  <div class=\"card\">
    <h2>Otonom karar logu</h2>
    <div class=\"log\" id=\"rationaleLog\"><div>Bekleniyor…</div></div>
  </div>
  <div class=\"card\">
    <h2>Coin board</h2>
    <div id=\"coinBoard\">—</div>
    <div class=\"lbl\" style=\"margin-top:10px\">Last skip</div>
    <div id=\"lastSkip\" class=\"log\" style=\"max-height:70px\">—</div>
  </div>
</div>
<div class=\"card\" style=\"margin-top:10px\">
  <h2>İşlemler</h2>
  <table class=\"table\"><thead><tr><th>t</th><th>side</th><th>qty</th><th>px</th><th>pnl</th><th>fee</th></tr></thead>
  <tbody id=\"fills\"></tbody></table>
</div>
<div class=\"foot\">Retail desk · HFT co-lo değil. Spoof=1.5s kalıcılık. BTC wick → altcoin kilidi. Dinamik TP/SL ATR×rejim.</div>
</main>
<script>
const el=id=>document.getElementById(id);
const num=(v,d=2)=>{const n=Number(v);return Number.isFinite(n)?n.toFixed(d):'—'};
let lastFlash=0;
function setGauge(score){
  const s=Math.max(0,Math.min(1,Number(score)||0));
  const deg=Math.round(s*360);
  const col=s>=0.65?'#39ff98':(s>=0.4?'#ffd166':'#3a5a48');
  el('gauge').style.background=`conic-gradient(${col} 0deg, ${col} ${deg}deg, #1a2e24 ${deg}deg)`;
  el('scoreVal').textContent=s.toFixed(2);
  el('scoreBar').style.width=(s*100).toFixed(0)+'%';
}
async function tick(){
  try{
    const r=await fetch('/status',{cache:'no-store'});const s=await r.json();
    const m=s.market||{},p=s.portfolio||{},pol=s.autonomous_policy||{},of=s.order_flow||{};
    const spo=s.spoof_report||{},btc=s.btc_filter||{},goal=s.goal||{};
    el('modePill').textContent=String(s.mode||s.trading_mode||'paper').toUpperCase();
    el('symPill').textContent=String(s.active_symbol||s.symbol||m.symbol||'—').toUpperCase();
    el('btcPill').textContent=btc.block_long?'BTC LOCK':'BTC OK';
    el('btcPill').className='pill'+(btc.block_long?' bad':'');
    el('spoofPill').textContent=spo.detected?'SPOOF!':'spoof ok';
    el('spoofPill').className='pill'+(spo.detected?' bad':'');
    el('goalPill').textContent=goal.halt?'GOAL HIT':(goal.note||'goal');
    el('goalPill').className='pill'+(goal.halt?' warn':'');
    const real=Number(p.realized_pnl_usdt||0);
    el('pnlCounter').textContent='$'+(Number.isFinite(real)?real:0).toFixed(2);
    el('pnlCounter').style.color=real>=0?'#39ff98':'#ff5c6c';
    el('equity').textContent=num(p.equity_usdt)+' USDT';
    el('realized').textContent='realized '+num(real)+' · fees '+num(p.fees_paid_usdt);
    el('upnl').textContent=num(p.unrealized_pnl_usdt);
    el('upnl').className='val '+(Number(p.unrealized_pnl_usdt)>=0?'pos':'neg');
    el('cash').textContent='cash '+num(p.cash_usdt);
    el('tpsl').textContent=(pol.tp!=null?num(pol.tp,2)+'% / '+num(pol.sl,2)+'%':'—');
    el('atrNote').textContent=pol.note||'—';
    el('flow').textContent=(of.ready?'READY ':'wait ')+num(of.pressure,2);
    el('regime').textContent=(s.analysis&&s.analysis.regime)||'—';
    const sc=s.signal_score!=null?s.signal_score:((s.last_decision&&s.last_decision.score)||(s.analysis&&s.analysis.score)||0);
    setGauge(sc);
    if(s.trade_flash || sc>=0.65){el('gaugeCard').classList.add('flash');el('flashMsg').textContent='TRADE BAND · score '+num(sc,2);lastFlash=Date.now()}
    else if(Date.now()-lastFlash>1200){el('gaugeCard').classList.remove('flash');el('flashMsg').textContent='score ≥ 0.65 → TRADE band'}
    const logs=s.rationale_log||[];
    el('rationaleLog').innerHTML=logs.length?logs.slice().reverse().map(x=>{
      const tx=String(x.text||x||'');
      const cls=tx.includes('SPOOF')||tx.includes('LOCK')?'bad':(tx.includes('READY')?'hi':'');
      return '<div class=\"'+cls+'\">'+tx.replace(/[<>]/g,'')+'</div>';
    }).join(''):'<div>'+(s.decision_rationale||'Bekleniyor…').replace(/[<>]/g,'')+'</div>';
    const board=s.symbol_leaderboard||[];
    el('coinBoard').innerHTML=board.length?board.slice(0,5).map(x=>'<div style=\"display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #152019\"><span>'+String(x.symbol||'').toUpperCase()+'</span><b>'+num(x.score,3)+'</b></div>').join(''):'<span class=\"lbl\">Tek pair / skor yok</span>';
    el('lastSkip').textContent=s.last_skip||'—';
    const fills=s.recent_fills||[];
    el('fills').innerHTML=fills.length?fills.slice(0,10).map(t=>{
      const pnl=Number(t.pnl_usdt);return '<tr><td>'+String(t.timestamp||'').slice(11,19)+'</td><td>'+String(t.side||'').toUpperCase()+'</td><td>'+num(t.quantity,5)+'</td><td>'+num(t.price,4)+'</td><td class=\"'+(pnl>=0?'pos':'neg')+'\">'+num(pnl,3)+'</td><td>'+num(t.fee_usdt,4)+'</td></tr>';
    }).join(''):'<tr><td colspan=6 class=lbl>İşlem yok</td></tr>';
  }catch(e){console.warn(e)}
}
setInterval(tick,900);tick();
</script></body></html>
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="Nexora Quant",
    version="0.1.0",
    description="Local dashboard and API for research / live desk.",
    lifespan=lifespan,
)

@app.middleware("http")
async def restrict_remote_access(request: Request, call_next):
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
    from app.config import settings as _s
    return {"status": "ok", "mode": getattr(_s, "trading_mode", "paper")}


@app.get("/status")
def status() -> dict:
    return state.snapshot()


@app.get("/portfolio")
def portfolio() -> dict:
    mark = state.latest_book.bid if state.latest_book else None
    return state.executor.snapshot(mark) if state.executor else {"status": "not_started"}
