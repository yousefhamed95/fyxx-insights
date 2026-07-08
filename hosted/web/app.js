/* Fyxx Executive Insights — hosted engine.
   All aggregation happens client-side from the exporter's JSON.
   Timezone: Asia/Amman = UTC+3 fixed (no DST since 2022). */
"use strict";

const TZ_OFF = 3 * 3600;                     // seconds
const CURRENCY = "JOD";
const PAL = {
  bg:"#0A0A0B", surface:"#111114", surface2:"#16161B", border:"#23232B",
  text:"#F4F4F5", dim:"#A1A1AA", muted:"#71717A", neon:"#19E3B6",
  amber:"#F5B544", rose:"#EC4899", violet:"#A78BFA", sky:"#38BDF8",
  good:"#22C55E", bad:"#F87171",
};
const CHANNEL_COLORS = {"E-com":"#19E3B6","Retail":"#38BDF8","TGR":"#A78BFA","B2B":"#F5B544","DF":"#EC4899"};
const COLORWAY = ["#19E3B6","#F5B544","#A78BFA","#38BDF8","#EC4899","#22C55E","#F87171","#FBBF24"];
const YEAR_COLORS = ["#38BDF8","#22C55E","#EC4899","#F5B544","#A78BFA","#19E3B6"];
const CH_ORDER = ["E-com","Retail","TGR","B2B","DF"];
const SHIFT_DAY = "Day · 10–17", SHIFT_EVE = "Evening · 17–01", SHIFT_OFF = "Off · 01–10";
const SHIFT_COLORS = {[SHIFT_DAY]:"#F5B544",[SHIFT_EVE]:"#A78BFA",[SHIFT_OFF]:"#3F3F46"};
const SUPPLIER_HIGHLIGHT = ["UMG","Fyxx","Zumot","Arab Italian","YHC"];

let D = {};            // loaded datasets
let O = [];            // orders as row objects
let SS = [];           // draft/cancel rows
let DLV = [];          // deliveries
let state = { scope:"MTD", channels:new Set(), custom:[null,null], tab:"overview" };

/* ---------------- time helpers ---------------- */
function local(ts){ return new Date((ts + TZ_OFF) * 1000); }   // use getUTC* on this
function dayKey(ts){ const d = local(ts);
  return d.getUTCFullYear()+"-"+String(d.getUTCMonth()+1).padStart(2,"0")+"-"+String(d.getUTCDate()).padStart(2,"0"); }
function monthKey(ts){ return dayKey(ts).slice(0,7); }
function todayLocal(){ const d = new Date(Date.now() + TZ_OFF*1000);
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate())); }
function dkOf(dateUTC){ return dateUTC.toISOString().slice(0,10); }
function addDays(dateUTC, n){ return new Date(dateUTC.getTime() + n*86400000); }
function parseDK(dk){ return new Date(dk + "T00:00:00Z"); }
function fmtDay(dk){ const d = parseDK(dk);
  return d.toLocaleDateString("en-GB",{weekday:"short",day:"2-digit",month:"short",timeZone:"UTC"}); }
function shiftOf(h){ if (h>=10 && h<17) return SHIFT_DAY; if (h>=17 || h<1) return SHIFT_EVE; return SHIFT_OFF; }

/* ---------------- formatting ---------------- */
function fmtM(n, compact){
  if (n===null || n===undefined || isNaN(n)) return "—";
  if (compact){
    if (Math.abs(n)>=1e6) return (n/1e6).toFixed(2)+"M "+CURRENCY;
    if (Math.abs(n)>=1e3) return (n/1e3).toFixed(1)+"K "+CURRENCY;
  }
  return Math.round(n).toLocaleString("en-US")+" "+CURRENCY;
}
function fmtN(n){ return Math.round(n).toLocaleString("en-US"); }
function deltaHtml(cur, prev, label){
  if (!prev) return "<span style='color:var(--muted)'>no prior data</span>";
  const p = (cur-prev)/prev*100;
  const cls = p>=0 ? "up":"dn", ar = p>=0 ? "▲":"▼";
  return `<span class='${cls}'>${ar} ${Math.abs(p).toFixed(1)}%</span> <span style='color:var(--muted)'>${label||""}</span>`;
}
function kpi(label, value, sub, foot){
  return `<div class='kpi'><div class='kpi-label'>${label}</div>`+
    `<div class='kpi-value'>${value}</div>`+
    (sub?`<div class='kpi-sub'>${sub}</div>`:"")+
    (foot?`<div class='kpi-foot'>${foot}</div>`:"")+`</div>`;
}
function fmtH(h){
  if (h===null||h===undefined||isNaN(h)) return "—";
  if (h < 1) return Math.round(h*60)+" min";
  if (h < 48) return h.toFixed(1)+" h";
  return (h/24).toFixed(1)+" d";
}
function median(xs){ if(!xs.length) return null; const s=[...xs].sort((a,b)=>a-b);
  const n=s.length; return n%2 ? s[(n-1)/2] : (s[n/2-1]+s[n/2])/2; }
function quant(xs,q){ if(!xs.length) return null; const s=[...xs].sort((a,b)=>a-b);
  return s[Math.min(s.length-1, Math.round(q*(s.length-1)))]; }

/* ---------------- plotly helpers ---------------- */
const PCONF = {displayModeBar:false, responsive:true};
function baseLayout(h, legend){
  return {
    height:h, paper_bgcolor:PAL.surface, plot_bgcolor:PAL.surface,
    font:{family:"Inter, sans-serif", color:PAL.dim, size:11.5},
    colorway:COLORWAY, margin:{l:46,r:14,t:12,b:34},
    showlegend:!!legend,
    legend:{orientation:"h", y:-0.18, x:0, font:{size:11, color:PAL.dim}, bgcolor:"rgba(0,0,0,0)"},
    xaxis:{showgrid:false, tickfont:{size:10.5, color:PAL.muted}},
    yaxis:{gridcolor:"rgba(255,255,255,0.045)", griddash:"dot", tickfont:{size:10.5,color:PAL.muted}, zeroline:false},
    hoverlabel:{bgcolor:PAL.surface2, bordercolor:"#2D2D37", font:{color:PAL.text, family:"Inter", size:12}},
  };
}
function plot(el, traces, layout){ Plotly.newPlot(el, traces, layout, PCONF); }

/* ---------------- data load ---------------- */
async function loadAll(){
  const names = ["meta","orders","sostates","delivery","products","pnl"];
  const res = await Promise.all(names.map(n => fetch("data.php?f="+n).then(r=>{
    if(!r.ok) throw new Error(n+" "+r.status); return r.json(); })));
  names.forEach((n,i)=> D[n]=res[i]);

  const od = D.orders;
  O = od.ts.map((ts,i)=>{
    const l = local(ts), h = l.getUTCHours();
    return { ts, dk:dayKey(ts), mk:monthKey(ts), y:l.getUTCFullYear(),
      m:l.getUTCMonth()+1, h, dow:(l.getUTCDay()+6)%7,     // 0=Mon
      shift:shiftOf(h),
      ch:od.channels[od.ch[i]], cu:od.customers[od.cu[i]],
      sp:od.salespeople[od.sp[i]], amt:od.amt[i], vat:od.vat[i],
      mg:od.mg[i], src:od.src[i] };
  });
  SS = D.sostates.ts.map((ts,i)=>({ ts, dk:dayKey(ts),
    ch:D.sostates.channels[D.sostates.ch[i]], st:D.sostates.st[i] }));
  DLV = D.delivery.ots.map((ots,i)=>{
    const dts = D.delivery.dts[i];
    return { ots, dts, dk:dayKey(ots), doneDk: dts?dayKey(dts):null,
      doneH: dts?local(dts).getUTCHours():null,
      h:local(ots).getUTCHours(), shift:shiftOf(local(ots).getUTCHours()),
      st:D.delivery.st[i], car:D.delivery.carriers[D.delivery.car[i]],
      ch:D.delivery.channels[D.delivery.ch[i]],
      lead: dts && dts>=ots && (dts-ots)<120*86400 ? (dts-ots)/3600 : null };
  });

  const chans = [...new Set(O.map(r=>r.ch))];
  chans.sort((a,b)=>{ const ia=CH_ORDER.indexOf(a), ib=CH_ORDER.indexOf(b);
    return (ia<0?99:ia)-(ib<0?99:ib); });
  state.channels = new Set(chans);
  state.allChannels = chans;

  document.getElementById("lastupd").textContent =
    "Data updated " + D.meta.generated_at + " (Amman)";
}

/* ---------------- scope windows ---------------- */
function scopeWindow(){
  const t = todayLocal();
  let cs, ce, ps, pe, label;
  if (state.scope==="Today"){ cs=ce=t; ps=pe=addDays(t,-1); label="Today"; }
  else if (state.scope==="Yesterday"){ cs=ce=addDays(t,-1); ps=pe=addDays(t,-2); label="Yesterday"; }
  else if (state.scope==="MTD"){
    cs = new Date(Date.UTC(t.getUTCFullYear(), t.getUTCMonth(), 1)); ce = t;
    const el = Math.round((t-cs)/86400000);
    const prevLast = addDays(cs,-1);
    ps = new Date(Date.UTC(prevLast.getUTCFullYear(), prevLast.getUTCMonth(), 1));
    pe = addDays(ps, el); label="MTD";
  } else if (state.scope==="YTD"){
    cs = new Date(Date.UTC(t.getUTCFullYear(),0,1)); ce=t;
    ps = new Date(Date.UTC(t.getUTCFullYear()-1,0,1));
    pe = new Date(Date.UTC(t.getUTCFullYear()-1, t.getUTCMonth(), t.getUTCDate()));
    label = "YTD "+t.getUTCFullYear();
  } else {   // Custom
    cs = state.custom[0]?parseDK(state.custom[0]):new Date(Date.UTC(t.getUTCFullYear(),0,1));
    ce = state.custom[1]?parseDK(state.custom[1]):t;
    const span = Math.round((ce-cs)/86400000);
    pe = addDays(cs,-1); ps = addDays(pe,-span);
    label = dkOf(cs)+" → "+dkOf(ce);
  }
  return {cs:dkOf(cs), ce:dkOf(ce), ps:dkOf(ps), pe:dkOf(pe), label,
          days: Math.round((parseDK(dkOf(ce))-parseDK(dkOf(cs)))/86400000)+1};
}
function inWin(r, a, b){ return r.dk>=a && r.dk<=b; }
function chOK(r){ return state.channels.has(r.ch); }

/* ---------------- UI scaffolding ---------------- */
const SCOPES = ["Today","Yesterday","MTD","YTD","Custom"];
const TABS = [["overview","◆ Overview"],["channels","⌬ Channels"],["customers","◐ Customers"],
              ["shifts","◷ Online & Shifts"],["products","❒ Products"],["pnl","Σ P&L"]];

function buildFilters(){
  const sp = document.getElementById("scopePills");
  sp.innerHTML = SCOPES.map(s=>`<button class="pill ${s===state.scope?"on":""}" data-s="${s}">${s}</button>`).join("");
  sp.querySelectorAll(".pill").forEach(b=>b.onclick=()=>{
    state.scope=b.dataset.s;
    document.getElementById("customDates").classList.toggle("show", state.scope==="Custom");
    buildFilters(); render(); });
  const cp = document.getElementById("chPills");
  cp.innerHTML = state.allChannels.map(c=>
    `<button class="pill ${state.channels.has(c)?"on":""}" data-c="${c}">${c}</button>`).join("");
  cp.querySelectorAll(".pill").forEach(b=>b.onclick=()=>{
    const c=b.dataset.c;
    if (state.channels.has(c)) state.channels.delete(c); else state.channels.add(c);
    if (!state.channels.size) state.allChannels.forEach(x=>state.channels.add(x));
    buildFilters(); render(); });
  document.getElementById("customDates").classList.toggle("show", state.scope==="Custom");
  document.getElementById("dApply").onclick=()=>{
    state.custom=[document.getElementById("dFrom").value||null,
                  document.getElementById("dTo").value||null];
    render(); };
  const tb = document.getElementById("tabs");
  tb.innerHTML = TABS.map(([id,l])=>`<button class="tab ${id===state.tab?"on":""}" data-t="${id}">${l}</button>`).join("");
  tb.querySelectorAll(".tab").forEach(b=>b.onclick=()=>{ state.tab=b.dataset.t; buildFilters(); render(); });
}

/* ---------------- KPI strip ---------------- */
function renderKPIs(w){
  const cur = O.filter(r=>chOK(r)&&inWin(r,w.cs,w.ce));
  const prv = O.filter(r=>chOK(r)&&inWin(r,w.ps,w.pe));
  const S = a=>a.reduce((x,r)=>x+r.amt,0), V=a=>a.reduce((x,r)=>x+r.vat,0), M=a=>a.reduce((x,r)=>x+r.mg,0);
  const rev=S(cur), prev=S(prv), vat=V(cur), gross=rev+vat, pgross=S(prv)+V(prv);
  const profit=M(cur), gm=rev?profit/rev*100:0, pgm=S(prv)?M(prv)/S(prv)*100:0;
  const orders=cur.length, porders=prv.length;
  const aov=orders?rev/orders:0, paov=porders?S(prv)/porders:0;
  const custs=new Set(cur.map(r=>r.cu)).size, pcusts=new Set(prv.map(r=>r.cu)).size;
  const gmPpt = gm-pgm;
  const gmDelta = pgm ? `<span class='${gmPpt>=0?"up":"dn"}'>${gmPpt>=0?"▲":"▼"} ${Math.abs(gmPpt).toFixed(1)} ppt</span> <span style='color:var(--muted)'>vs prior</span>`
                      : "<span style='color:var(--muted)'>no prior data</span>";
  document.getElementById("kpis").innerHTML =
    kpi("Net Amount", fmtM(rev,true), deltaHtml(rev,prev,"vs prior period"), "Prior: "+fmtM(prev,true)) +
    kpi("Net + VAT", fmtM(gross,true), deltaHtml(gross,pgross,"vs prior period"), "VAT: "+fmtM(vat,true)) +
    kpi("Gross margin", gm.toFixed(1)+"%", gmDelta, "Profit: "+fmtM(profit,true)) +
    kpi("Orders", fmtN(orders), deltaHtml(orders,porders,"vs prior period"), "Prior: "+fmtN(porders)) +
    kpi("Avg order value", orders?fmtM(aov):"—", deltaHtml(aov,paov,"vs prior period"), "Prior: "+fmtM(paov)) +
    kpi("Active customers", fmtN(custs), deltaHtml(custs,pcusts,"vs prior period"), "Prior: "+fmtN(pcusts));
  return {cur, prv, rev, prev};
}

/* ---------------- Overview ---------------- */
function renderOverview(el, w, ctx){
  const {cur, prv, rev, prev} = ctx;
  // brief
  const chRev = group(cur, r=>r.ch, r=>r.amt);
  const topCh = Object.entries(chRev).sort((a,b)=>b[1]-a[1])[0];
  const cuRev = group(cur.filter(r=>r.cu!=="Walk-in"), r=>r.cu, r=>r.amt);
  const topCu = Object.entries(cuRev).sort((a,b)=>b[1]-a[1])[0];
  const byDay = group(cur, r=>r.dk, r=>r.amt);
  const bestDay = Object.entries(byDay).sort((a,b)=>b[1]-a[1])[0];
  const pct = prev ? ((rev-prev)/prev*100) : null;
  let brief = `<b>${w.label}</b> net revenue is <b style="color:var(--neon)">${fmtM(rev)}</b>`;
  if (pct!==null) brief += `, <b class="${pct>=0?"up":"dn"}">${pct>=0?"+":"−"}${Math.abs(pct).toFixed(1)}%</b> vs the prior period (${fmtM(prev)})`;
  brief += ` across <b>${fmtN(cur.length)}</b> orders.`;
  if (topCh) brief += ` <b>${topCh[0]}</b> leads channels with ${fmtM(topCh[1],true)} (${(topCh[1]/rev*100||0).toFixed(0)}%).`;
  if (topCu) brief += ` Top customer: <b>&#8206;${esc(topCu[0])}</b> (${fmtM(topCu[1],true)}).`;
  if (bestDay) brief += ` Best day: <b>${fmtDay(bestDay[0])}</b> with ${fmtM(bestDay[1],true)}.`;

  el.innerHTML =
    `<div class="insight"><div class="t">◆ Executive brief</div><div class="brieftext">${brief}</div></div>`+
    sec("Monthly revenue · year-over-year","Same calendar month, compared across years")+
    `<div class="card"><div class="chart" id="ovYoY"></div></div>
     <div class="grid2" style="margin-top:14px">
       <div><div class="sec"><h3>Daily revenue · ${w.label}</h3><div class="sub">Net of VAT</div></div>
         <div class="card"><div class="chart" id="ovDaily"></div></div></div>
       <div><div class="sec"><h3>Day-of-week × hour heatmap</h3><div class="sub">${w.label}</div></div>
         <div class="card"><div class="chart" id="ovHeat"></div></div></div>
     </div>`;

  // YoY chart (channel-filtered, all data)
  const years = [...new Set(O.filter(chOK).map(r=>r.y))].sort();
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const traces = years.map((y,i)=>{
    const vals = Array(12).fill(0);
    O.filter(r=>chOK(r)&&r.y===y).forEach(r=>vals[r.m-1]+=r.amt);
    const color = y===todayLocal().getUTCFullYear() ? PAL.neon : YEAR_COLORS[i%YEAR_COLORS.length];
    return {x:months, y:vals.map(v=>Math.round(v)), name:String(y), mode:"lines+markers",
      line:{width:2.4, color, shape:"spline", smoothing:.6}, marker:{size:6,color}};
  });
  plot("ovYoY", traces, baseLayout(360, true));

  // daily bars
  const dks = Object.keys(byDay).sort();
  plot("ovDaily", [{x:dks, y:dks.map(k=>Math.round(byDay[k])), type:"bar",
    marker:{color:PAL.neon}}], baseLayout(300,false));

  // heatmap
  const dows = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
  const z = dows.map((_,d)=>Array.from({length:24},(_,h)=>{
    let s=0; cur.forEach(r=>{ if(r.dow===d&&r.h===h) s+=r.amt; }); return Math.round(s); }));
  plot("ovHeat", [{z, x:Array.from({length:24},(_,h)=>String(h).padStart(2,"0")), y:dows,
    type:"heatmap", colorscale:[[0,"#0A0A0B"],[0.4,"#0E5A4A"],[1,"#19E3B6"]], showscale:false,
    xgap:1, ygap:2}], baseLayout(300,false));
}

/* ---------------- Channels ---------------- */
function renderChannels(el, w, ctx){
  const {cur, prv} = ctx;
  const cRev = group(cur, r=>r.ch, r=>r.amt), pRev = group(prv, r=>r.ch, r=>r.amt);
  const chans = [...new Set([...Object.keys(cRev),...Object.keys(pRev)])]
    .sort((a,b)=>(cRev[b]||0)-(cRev[a]||0));
  el.innerHTML =
    sec("Channel performance · current vs prior","Side-by-side, net of VAT")+
    `<div class="card"><div class="chart" id="chBars"></div></div>`+
    sec("Channel ranking","")+
    `<div class="card" style="padding:12px" id="chTable"></div>`;
  plot("chBars", [
    {x:chans, y:chans.map(c=>Math.round(pRev[c]||0)), name:"Prior", type:"bar",
     marker:{color:"rgba(161,161,170,0.35)"}},
    {x:chans, y:chans.map(c=>Math.round(cRev[c]||0)), name:"Current", type:"bar",
     marker:{color:chans.map(c=>CHANNEL_COLORS[c]||PAL.neon)}},
  ], Object.assign(baseLayout(340,true),{barmode:"group"}));
  const tot = Object.values(cRev).reduce((a,b)=>a+b,0)||1;
  let rows = "";
  chans.forEach(c=>{
    const cc = cur.filter(r=>r.ch===c);
    const revC = cRev[c]||0, n=cc.length, mg=cc.reduce((x,r)=>x+r.mg,0);
    const d = pRev[c] ? ((revC-pRev[c])/pRev[c]*100) : null;
    rows += `<tr><td><span style="color:${CHANNEL_COLORS[c]||PAL.text}">●</span> ${c}</td>
      <td>${fmtM(revC)}</td><td>${(revC/tot*100).toFixed(1)}%</td><td>${fmtN(n)}</td>
      <td>${n?fmtM(revC/n):"—"}</td><td>${revC?(mg/revC*100).toFixed(1):"0.0"}%</td>
      <td>${d===null?"—":`<span class="${d>=0?"up":"dn"}">${d>=0?"▲":"▼"} ${Math.abs(d).toFixed(1)}%</span>`}</td></tr>`;
  });
  document.getElementById("chTable").innerHTML =
    `<table class="tbl"><thead><tr><th>Channel</th><th>Net revenue</th><th>Share</th>
     <th>Orders</th><th>AOV</th><th>GM%</th><th>vs prior</th></tr></thead><tbody>${rows}</tbody></table>`;
}

/* ---------------- Customers ---------------- */
function renderCustomers(el, w, ctx){
  const {cur} = ctx;
  const named = cur.filter(r=>r.cu!=="Walk-in" && r.cu!=="—");
  const agg = {};
  named.forEach(r=>{ const a=agg[r.cu]=agg[r.cu]||{n:0,rev:0,mg:0};
    a.n++; a.rev+=r.amt; a.mg+=r.mg; });
  const top = Object.entries(agg).sort((a,b)=>b[1].rev-a[1].rev).slice(0,20);
  const spAgg = {};
  cur.forEach(r=>{ const a=spAgg[r.sp]=spAgg[r.sp]||{n:0,rev:0};
    a.n++; a.rev+=r.amt; });
  const spTop = Object.entries(spAgg).sort((a,b)=>b[1].rev-a[1].rev).slice(0,10);
  el.innerHTML =
    sec("Top 20 customers","Named customers, net of VAT · "+w.label)+
    `<div class="card" style="padding:12px"><table class="tbl"><thead><tr>
      <th>#</th><th>Customer</th><th>Orders</th><th>Net revenue</th><th>AOV</th><th>Margin</th><th>GM%</th>
     </tr></thead><tbody>`+
    top.map(([cu,a],i)=>`<tr><td>${i+1}</td><td>&#8206;${esc(cu)}</td><td>${fmtN(a.n)}</td>
      <td>${fmtM(a.rev)}</td><td>${fmtM(a.rev/a.n)}</td><td>${fmtM(a.mg)}</td>
      <td>${a.rev?(a.mg/a.rev*100).toFixed(1):"0.0"}%</td></tr>`).join("")+
    `</tbody></table></div>`+
    sec("Top salespeople","By net revenue · "+w.label)+
    `<div class="card" style="padding:12px"><table class="tbl"><thead><tr>
      <th>Salesperson</th><th>Orders</th><th>Net revenue</th></tr></thead><tbody>`+
    spTop.map(([sp,a])=>`<tr><td>&#8206;${esc(sp)}</td><td>${fmtN(a.n)}</td><td>${fmtM(a.rev)}</td></tr>`).join("")+
    `</tbody></table></div>`;
}

/* ---------------- Online & Shifts (with delivery + fleet) ---------------- */
function renderShifts(el, w, ctx){
  const {cur, prv} = ctx;
  const days = [];
  for (let d=parseDK(w.cs); d<=parseDK(w.ce); d=addDays(d,1)) days.push(dkOf(d));
  const showLbl = days.length<=16;
  const isOnline = state.channels.size===1 && state.channels.has("E-com");
  const noun = isOnline ? "online orders" : "orders";
  const sc = (a,s)=>a.filter(r=>r.shift===s).length;
  const nDay=sc(cur,SHIFT_DAY), nEve=sc(cur,SHIFT_EVE), nOff=sc(cur,SHIFT_OFF);
  const pDay=sc(prv,SHIFT_DAY), pEve=sc(prv,SHIFT_EVE);
  const drafts = SS.filter(r=>state.channels.has(r.ch)&&inWin(r,w.cs,w.ce)&&r.st<=1);
  const cancels = SS.filter(r=>state.channels.has(r.ch)&&inWin(r,w.cs,w.ce)&&r.st===2);
  const byDay = {}; cur.forEach(r=>byDay[r.dk]=(byDay[r.dk]||0)+1);
  const busiest = Object.entries(byDay).sort((a,b)=>b[1]-a[1])[0];

  // insights
  const ins = [];
  if (cur.length){
    const dom = nEve>=nDay ? ["evening",nEve,nDay] : ["day",nDay,nEve];
    ins.push(`The <b>${dom[0]} shift</b> drives <b>${(dom[1]/cur.length*100).toFixed(0)}%</b> of ${noun} — <b>${fmtN(dom[1])}</b> vs <b>${fmtN(dom[2])}</b>.`);
    const byH = {}; cur.forEach(r=>byH[r.h]=(byH[r.h]||0)+1);
    const pk = Object.entries(byH).sort((a,b)=>b[1]-a[1])[0];
    if (pk) ins.push(`Peak hour is <b>${String(pk[0]).padStart(2,"0")}:00</b> with <b>${fmtN(pk[1])}</b> orders.`);
    if (prv.length){ const d=(cur.length-prv.length)/prv.length*100;
      ins.push(`Volume is <b>${d>=0?"up":"down"} ${Math.abs(d).toFixed(0)}%</b> vs the prior period (${fmtN(cur.length)} vs ${fmtN(prv.length)}).`); }
    if (busiest) ins.push(`Busiest day <b>${fmtDay(busiest[0])}</b> (${fmtN(busiest[1])}).`);
    const placed = cur.length + cancels.length;
    if (placed) ins.push(`<b>${fmtN(cancels.length)}</b> orders were cancelled — <b>${(cancels.length/placed*100).toFixed(0)}%</b> of all placed.`);
    ins.push(drafts.length ? `<b>${fmtN(drafts.length)}</b> draft quotation(s) pending in Odoo.` : "No draft quotations pending in Odoo.");
  } else ins.push(`No ${noun} matched the current filters.`);

  el.innerHTML =
    sec((isOnline?"Online orders":"Orders")+" & shift analytics",
        `${w.label} · ${w.cs} → ${w.ce} (${w.days} days) · Day 10:00–17:00 · Evening 17:00–01:00`)+
    `<div class="kpi-grid">`+
    kpi("Orders · period", fmtN(cur.length), deltaHtml(cur.length,prv.length,"vs prior"), "Prior: "+fmtN(prv.length))+
    kpi("Day shift · 10–17", fmtN(nDay), deltaHtml(nDay,pDay,"vs prior"), cur.length?(nDay/cur.length*100).toFixed(0)+"% of orders":"")+
    kpi("Evening shift · 17–01", fmtN(nEve), deltaHtml(nEve,pEve,"vs prior"), cur.length?(nEve/cur.length*100).toFixed(0)+"% of orders":"")+
    kpi("Busiest day", busiest?fmtDay(busiest[0]):"—", busiest?fmtN(busiest[1])+" orders":"", "Avg "+(cur.length/w.days).toFixed(1)+"/day")+
    kpi("Draft orders", fmtN(drafts.length), "", "Odoo quotations (draft/sent)")+
    kpi("Cancelled", fmtN(cancels.length), "", "orders placed then voided")+
    `</div>`+
    `<div class="insight"><div class="t">◆ Smart insights</div><ul>${ins.map(t=>`<li>${t}</li>`).join("")}</ul></div>`+
    sec("Daily orders by shift","Stacked — day vs evening vs off-hours")+
    `<div class="card"><div class="chart" id="shStack"></div></div>
     <div class="grid23" style="margin-top:14px">
       <div><div class="sec"><h3>Shift split</h3></div><div class="card"><div class="chart" id="shDonut"></div></div></div>
       <div><div class="sec"><h3>Orders by hour of day</h3></div><div class="card"><div class="chart" id="shHours"></div></div></div>
     </div>`+
    sec("Order intensity · weekday × hour","Aggregated across the period")+
    `<div class="card"><div class="chart" id="shHeat"></div></div>`+
    sec("Per-day breakdown","Orders by shift, plus drafts & cancellations")+
    `<div class="card" style="padding:12px" id="shTable"></div>`+
    `<div id="shDelivery"></div>`;

  // stacked
  const shifts = [SHIFT_DAY, SHIFT_EVE, SHIFT_OFF];
  const stackTraces = shifts.map(s=>{
    const y = days.map(dk=>cur.filter(r=>r.dk===dk&&r.shift===s).length);
    if (s===SHIFT_OFF && y.every(v=>!v)) return null;
    return {x:days.map(fmtDay), y, name:s, type:"bar", marker:{color:SHIFT_COLORS[s]},
      text: showLbl ? y.map(v=>v||"") : undefined, textposition:"inside"};
  }).filter(Boolean);
  plot("shStack", stackTraces, Object.assign(baseLayout(340,true),{barmode:"stack"}));
  // donut
  const dl=[SHIFT_DAY,SHIFT_EVE], dv=[nDay,nEve], dc=[SHIFT_COLORS[SHIFT_DAY],SHIFT_COLORS[SHIFT_EVE]];
  if (nOff){ dl.push(SHIFT_OFF); dv.push(nOff); dc.push(SHIFT_COLORS[SHIFT_OFF]); }
  plot("shDonut", [{labels:dl, values:dv, type:"pie", hole:.64, sort:false,
    marker:{colors:dc, line:{color:PAL.surface,width:2}}, textinfo:"percent"}],
    Object.assign(baseLayout(290,true),{annotations:[{text:`<b>${fmtN(cur.length)}</b><br><span style="font-size:10px">orders</span>`,
      x:.5,y:.5,showarrow:false,font:{size:18,color:PAL.text}}]}));
  // hourly
  const hv = Array.from({length:24},(_,h)=>cur.filter(r=>r.h===h).length);
  plot("shHours", [{x:Array.from({length:24},(_,h)=>String(h).padStart(2,"0")), y:hv, type:"bar",
    marker:{color:Array.from({length:24},(_,h)=>SHIFT_COLORS[shiftOf(h)])}}], baseLayout(290,false));
  // heatmap
  const dows=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
  const z = dows.map((_,d)=>Array.from({length:24},(_,h)=>cur.filter(r=>r.dow===d&&r.h===h).length));
  plot("shHeat",[{z, x:Array.from({length:24},(_,h)=>String(h).padStart(2,"0")), y:dows, type:"heatmap",
    colorscale:[[0,"#0A0A0B"],[0.45,"#3a2f5e"],[1,"#A78BFA"]], showscale:false, xgap:1, ygap:2}],
    baseLayout(290,false));
  // table
  const shown = days.length>45 ? days.slice(-45) : days;
  let tot={d:0,e:0,o:0,t:0,dr:0,cn:0}, body="";
  shown.forEach(dk=>{
    const dd = cur.filter(r=>r.dk===dk);
    const a=sc(dd,SHIFT_DAY), b=sc(dd,SHIFT_EVE), c=sc(dd,SHIFT_OFF);
    const dr = drafts.filter(r=>r.dk===dk).length, cn = cancels.filter(r=>r.dk===dk).length;
    tot.d+=a;tot.e+=b;tot.o+=c;tot.t+=a+b+c;tot.dr+=dr;tot.cn+=cn;
    body+=`<tr><td>${fmtDay(dk)}</td><td>${a}</td><td>${b}</td><td>${c}</td><td><b>${a+b+c}</b></td><td>${dr}</td><td>${cn}</td></tr>`;
  });
  body+=`<tr class="tot"><td>Total</td><td>${tot.d}</td><td>${tot.e}</td><td>${tot.o}</td><td>${tot.t}</td><td>${tot.dr}</td><td>${tot.cn}</td></tr>`;
  document.getElementById("shTable").innerHTML =
    `<table class="tbl"><thead><tr><th>Date</th><th>Day 10–17</th><th>Evening 17–01</th>
     <th>Off 01–10</th><th>Total</th><th>Draft</th><th>Cancelled</th></tr></thead><tbody>${body}</tbody></table>`;

  renderDelivery(document.getElementById("shDelivery"), w, days, showLbl);
}

function renderDelivery(el, w, days, showLbl){
  const dd = DLV.filter(r=>state.channels.has(r.ch)&&inWin(r,w.cs,w.ce));
  const done = dd.filter(r=>r.st===0), pend = dd.filter(r=>r.st===1), canc = dd.filter(r=>r.st===2);
  const lead = done.map(r=>r.lead).filter(x=>x!==null);
  const med = median(lead), p90 = quant(lead,0.9);
  const w2 = lead.length?lead.filter(x=>x<=2).length/lead.length*100:0;
  const w24 = lead.length?lead.filter(x=>x<=24).length/lead.length*100:0;
  const carAgg = {}; dd.forEach(r=>carAgg[r.car]=(carAgg[r.car]||0)+1);
  const topCar = Object.entries(carAgg).sort((a,b)=>b[1]-a[1])[0];

  const ins=[];
  if (lead.length){
    ins.push(`Typical delivery completes in <b>${fmtH(med)}</b> (median); 90% land within <b>${fmtH(p90)}</b>.`);
    ins.push(`<b>${w2.toFixed(0)}%</b> of deliveries finish within 2 hours and <b>${w24.toFixed(0)}%</b> within a day.`);
    const slow = lead.filter(x=>x>48);
    if (slow.length) ins.push(`<b>${slow.length}</b> deliveries took over 2 days (slowest ${fmtH(Math.max(...lead))}) — worth investigating.`);
  }
  if (pend.length) ins.push(`<b>${pend.length}</b> deliveries are currently in transit / awaiting dispatch.`);
  if (canc.length) ins.push(`<b>${canc.length}</b> delivery orders were cancelled this period.`);
  if (!ins.length) ins.push("No delivery data in this period.");

  el.innerHTML =
    sec("Delivery performance","Real delivery orders (excludes in-store pickups) · lead time = order placed → delivery completed")+
    `<div class="kpi-grid">`+
    kpi("Deliveries · period", fmtN(dd.length), "", fmtN(done.length)+" completed")+
    kpi("Typical lead time", fmtH(med), "median order → delivered", "p90: "+fmtH(p90))+
    kpi("Within 2 hours", w2.toFixed(0)+"%", "of completed deliveries", "Within 24h: "+w24.toFixed(0)+"%")+
    kpi("In transit", fmtN(pend.length), "assigned / awaiting", "not yet delivered")+
    kpi("Top carrier", topCar?esc(topCar[0]):"—", topCar?(topCar[1]/dd.length*100).toFixed(0)+"% of deliveries":"", "")+
    kpi("Cancelled", fmtN(canc.length), "", "delivery orders voided")+
    `</div>`+
    `<div class="insight"><div class="t">◆ Delivery insights</div><ul>${ins.map(t=>`<li>${t}</li>`).join("")}</ul></div>`+
    `<div class="grid2" style="margin-top:14px">
       <div><div class="sec"><h3>Delivery-time distribution</h3></div><div class="card"><div class="chart" id="dlvBuckets"></div></div></div>
       <div><div class="sec"><h3>By carrier</h3></div><div class="card"><div class="chart" id="dlvCar"></div></div></div>
     </div>
     <div class="grid2" style="margin-top:14px">
       <div><div class="sec"><h3>Median delivery time by order shift</h3></div><div class="card"><div class="chart" id="dlvShift"></div></div></div>
       <div><div class="sec"><h3>Deliveries completed · daily</h3></div><div class="card"><div class="chart" id="dlvDaily"></div></div></div>
     </div>
     <div id="fleetTool"></div>`;

  if (lead.length){
    const bnames=["<1h","1–2h","2–6h","6–24h","1–2d",">2d"];
    const bc=[0,0,0,0,0,0];
    lead.forEach(h=>{ bc[h<1?0:h<2?1:h<6?2:h<24?3:h<48?4:5]++; });
    plot("dlvBuckets", [{x:bnames,y:bc,type:"bar",marker:{color:PAL.neon},
      text:bc.map(v=>v||""),textposition:"outside"}], baseLayout(290,false));
  }
  const ce = Object.entries(carAgg).sort((a,b)=>b[1]-a[1]);
  plot("dlvCar", [{labels:ce.map(x=>x[0]), values:ce.map(x=>x[1]), type:"pie", hole:.62,
    marker:{line:{color:PAL.surface,width:2}}, textinfo:"percent"}], baseLayout(290,true));
  const shifts=[SHIFT_DAY,SHIFT_EVE,SHIFT_OFF];
  const meds = shifts.map(s=>median(done.filter(r=>r.shift===s).map(r=>r.lead).filter(x=>x!==null)));
  const keep = shifts.map((s,i)=>[s,meds[i]]).filter(x=>x[1]!==null);
  plot("dlvShift", [{x:keep.map(x=>x[0].split(" ·")[0]), y:keep.map(x=>x[1]), type:"bar",
    marker:{color:keep.map(x=>SHIFT_COLORS[x[0]])}, text:keep.map(x=>fmtH(x[1])), textposition:"outside"}],
    baseLayout(290,false));
  const dcnt = days.map(dk=>done.filter(r=>r.doneDk===dk).length);
  plot("dlvDaily", [{x:days.map(fmtDay), y:dcnt, type:"bar", marker:{color:PAL.sky},
    text: showLbl?dcnt.map(v=>v||""):undefined, textposition:"outside"}], baseLayout(290,false));

  renderFleet(document.getElementById("fleetTool"), done);
}

function renderFleet(el, done){
  el.innerHTML =
    sec("Fleet capacity · do you need another delivery car?","Set the three inputs — the verdict recalculates live")+
    `<div class="fleet-inputs">
      <div><label>Delivery cars available now</label><input type="number" id="fCars" min="1" max="50" value="5"></div>
      <div><label>Round-trip minutes per delivery</label><input type="number" id="fRT" min="10" max="240" step="5" value="20"></div>
      <div><label>Orders carried per trip</label><input type="number" id="fBatch" min="1" max="10" value="1"></div>
    </div>
    <div class="kpi-grid" id="fKpis"></div>
    <div id="fVerdict"></div>
    <div class="sec"><h3>Hourly delivery demand vs fleet capacity</h3>
      <div class="sub">Avg deliveries completed per hour on an active day; bars above the line exceed capacity</div></div>
    <div class="card"><div class="chart" id="fChart"></div></div>`;
  const recalc = ()=>{
    const cars = +document.getElementById("fCars").value||5;
    const rt = +document.getElementById("fRT").value||20;
    const batch = +document.getElementById("fBatch").value||1;
    const dd2 = done.filter(r=>r.doneDk && r.doneH!==null);
    const byDay = {};
    dd2.forEach(r=>{ (byDay[r.doneDk]=byDay[r.doneDk]||{})[r.doneH]=(byDay[r.doneDk][r.doneH]||0)+1; });
    const peaks = Object.values(byDay).map(h=>Math.max(...Object.values(h)));
    const activeDays = peaks.length;
    const typical = activeDays?peaks.reduce((a,b)=>a+b,0)/activeDays:0;
    const p90 = activeDays?quant(peaks,0.9):0;
    const extreme = activeDays?Math.max(...peaks):0;
    const per = 60/rt*batch, fleet = cars*per;
    const reqT = per?Math.ceil(typical/per):0, reqW = per?Math.ceil(p90/per):0;
    const util = fleet?typical/fleet*100:0;
    const addP = Math.max(0, reqT-cars), addS = Math.max(0, reqW-cars);
    let head, big, txt, color;
    if (!addP && !addS){ head="No increase needed"; big="0"; color=PAL.good;
      txt=`Your <b>${cars}</b> cars cover both the typical peak (~${typical.toFixed(0)}/hr) and busy nights (${p90}/hr). Peak utilisation ${util.toFixed(0)}%. Keep the fleet as-is.`; }
    else if (!addP){ head="No permanent increase — keep cars on-call for spikes"; big=`+${addS} on-call`; color=PAL.amber;
      txt=`Your <b>${cars}</b> cars cover the typical peak (~${typical.toFixed(0)}/hr, ${util.toFixed(0)}% utilised). Busy nights (${p90}/hr) need up to <b>${reqW}</b> — keep <b>${addS}</b> on-call / part-time rather than buying permanently.`; }
    else { head=`Increase your fleet by ${addP} car(s)`; big=`+${addP}`; color=PAL.bad;
      txt=`Your <b>${cars}</b> cars are below the typical peak (~${typical.toFixed(0)}/hr) which needs <b>${reqT}</b>. Add <b>${addP}</b> permanently; busy nights (${p90}/hr) would need up to ${reqW}.`; }
    document.getElementById("fKpis").innerHTML =
      kpi("Cars now", cars, "current fleet", "Fleet capacity "+fleet.toFixed(1)+"/hr")+
      kpi("Typical peak demand", typical.toFixed(0)+"/hr", "avg of each day's busiest hour", `Busy night (p90): ${p90}/hr · max ${extreme}/hr`)+
      kpi("Recommended fleet", reqT, "to cover the typical peak", "Busy nights need "+reqW)+
      kpi("Cars to ADD", addP, "permanent, vs what you have", "Peak utilisation: "+util.toFixed(0)+"%")+
      kpi("On-call for spikes", addS, "extra cars for worst hours", "part-time / surge")+
      kpi("Capacity per car", per.toFixed(1)+"/hr", `at ${rt} min · ${batch}/trip`, "");
    document.getElementById("fVerdict").innerHTML =
      `<div class="verdict" style="border-color:${color}55">
        <div class="big" style="color:${color}">${big}<small>cars</small></div>
        <div><div class="vt" style="color:${color}">◆ Recommendation — ${head}</div>
        <div class="vb">${txt}</div></div></div>`;
    const prof = Array.from({length:24},(_,h)=>{
      let s=0; Object.values(byDay).forEach(day=>{ s+=day[h]||0; });
      return activeDays?s/activeDays:0; });
    plot("fChart", [{x:Array.from({length:24},(_,h)=>String(h).padStart(2,"0")),
      y:prof.map(v=>+v.toFixed(2)), type:"bar",
      marker:{color:prof.map(v=>v>fleet?PAL.bad:PAL.neon)}}],
      Object.assign(baseLayout(300,false),{shapes:[{type:"line",x0:-0.5,x1:23.5,y0:fleet,y1:fleet,
        line:{color:PAL.violet,width:2,dash:"dash"}}],
        annotations:[{x:0,y:fleet,xanchor:"left",yanchor:"bottom",showarrow:false,
          text:`capacity ${fleet.toFixed(1)}/hr`,font:{color:PAL.violet,size:11}}]}));
  };
  ["fCars","fRT","fBatch"].forEach(id=>document.getElementById(id).oninput=recalc);
  recalc();
}

/* ---------------- Products ---------------- */
function renderProducts(el, w){
  const months = new Set();
  for (let d=parseDK(w.cs); d<=parseDK(w.ce); d=addDays(d,1)) months.add(dkOf(d).slice(0,7));
  const P = D.products;
  const idx = P.months.map((m,i)=>months.has(m)?i:-1);
  const per = {};   // pid -> {q, r, g}
  P.rows.forEach(([mi,pi,q,r,g])=>{
    if (idx[mi]<0) return;
    const a = per[pi]=per[pi]||{q:0,r:0,g:0};
    a.q+=q; a.r+=r; a.g+=g;
  });
  const entries = Object.entries(per).map(([pi,a])=>({p:P.products[+pi],...a}))
    .sort((a,b)=>b.r-a.r);
  const top = entries.slice(0,20);
  const catAgg = {}, supAgg = {};
  entries.forEach(e=>{ catAgg[e.p.c]=(catAgg[e.p.c]||0)+e.r;
    const s = SUPPLIER_HIGHLIGHT.includes(e.p.s)?e.p.s:"Other";
    supAgg[s]=(supAgg[s]||0)+e.r; });

  el.innerHTML =
    sec("Top 20 SKUs by revenue", w.label+" · net of VAT")+
    `<div class="card" style="padding:12px"><table class="tbl"><thead><tr>
      <th>#</th><th>Product</th><th>Category</th><th>Supplier</th><th>Qty</th>
      <th>Revenue</th><th>Margin</th><th>GM%</th></tr></thead><tbody>`+
    top.map((e,i)=>`<tr><td>${i+1}</td><td>&#8206;${esc(e.p.n)}</td><td>${esc(e.p.c)}</td>
      <td>${esc(e.p.s)}</td><td>${fmtN(e.q)}</td><td>${fmtM(e.r)}</td>
      <td>${fmtM(e.g)}</td><td>${e.r?(e.g/e.r*100).toFixed(1):"0.0"}%</td></tr>`).join("")+
    `</tbody></table></div>
     <div class="grid2" style="margin-top:14px">
      <div><div class="sec"><h3>Revenue by category</h3></div><div class="card"><div class="chart" id="prCat"></div></div></div>
      <div><div class="sec"><h3>Revenue by supplier</h3><div class="sub">UMG · Fyxx · Zumot · Arab Italian · YHC highlighted</div></div>
        <div class="card"><div class="chart" id="prSup"></div></div></div>
     </div>
     <div class="note">Product figures aggregate by calendar month — a scope that starts or ends mid-month includes those whole months.</div>`;
  const cats = Object.entries(catAgg).sort((a,b)=>b[1]-a[1]).slice(0,12);
  plot("prCat", [{labels:cats.map(x=>x[0]), values:cats.map(x=>Math.round(x[1])), type:"pie",
    hole:.62, marker:{line:{color:PAL.surface,width:2}}, textinfo:"percent"}], baseLayout(320,true));
  const sups = Object.entries(supAgg).sort((a,b)=>b[1]-a[1]);
  plot("prSup", [{labels:sups.map(x=>x[0]), values:sups.map(x=>Math.round(x[1])), type:"pie",
    hole:.62, marker:{line:{color:PAL.surface,width:2}}, textinfo:"percent"}], baseLayout(320,true));
}

/* ---------------- P&L ---------------- */
function renderPnl(el, w){
  const months = [];
  const seen = new Set();
  for (let d=parseDK(w.cs); d<=parseDK(w.ce); d=addDays(d,1)){
    const m = dkOf(d).slice(0,7);
    if (!seen.has(m)){ seen.add(m); months.push(m); }
  }
  const revByM = {}; O.filter(chOK).forEach(r=>{ if(seen.has(r.mk)) revByM[r.mk]=(revByM[r.mk]||0)+r.amt; });
  const expRows = D.pnl.rows.filter(r=>seen.has(r.m));
  const buckets = [...new Set(expRows.map(r=>r.b))];
  const expByMB = {}; expRows.forEach(r=>{ expByMB[r.m+"|"+r.b]=r.v; });
  const expByM = {}; expRows.forEach(r=>{ expByM[r.m]=(expByM[r.m]||0)+r.v; });
  const totRev = Object.values(revByM).reduce((a,b)=>a+b,0);
  const totExp = Object.values(expByM).reduce((a,b)=>a+b,0);

  el.innerHTML =
    sec("Profit & Loss", w.label+" · revenue net of VAT vs posted expenses")+
    `<div class="kpi-grid">`+
    kpi("Revenue (net)", fmtM(totRev,true), "", "")+
    kpi("Expenses", fmtM(totExp,true), "", "posted journal entries")+
    kpi("Net result", fmtM(totRev-totExp,true),
        `<span class="${totRev-totExp>=0?"up":"dn"}">${totRev-totExp>=0?"positive":"negative"}</span>`, "")+
    kpi("Expense ratio", totRev?(totExp/totRev*100).toFixed(1)+"%":"—", "expenses / revenue", "")+
    `</div>`+
    sec("Monthly revenue vs expenses","")+
    `<div class="card"><div class="chart" id="plChart"></div></div>`+
    sec("Expense breakdown","By account group · "+w.label)+
    `<div class="card" style="padding:12px" id="plTable"></div>`+
    `<div class="note">Expense figures aggregate by calendar month.</div>`;

  plot("plChart", [
    {x:months, y:months.map(m=>Math.round(revByM[m]||0)), name:"Revenue", type:"bar", marker:{color:PAL.neon}},
    {x:months, y:months.map(m=>Math.round(expByM[m]||0)), name:"Expenses", type:"bar", marker:{color:PAL.rose}},
    {x:months, y:months.map(m=>Math.round((revByM[m]||0)-(expByM[m]||0))), name:"Net", mode:"lines+markers",
     line:{color:PAL.amber,width:2.4}, marker:{size:6,color:PAL.amber}},
  ], Object.assign(baseLayout(340,true),{barmode:"group"}));

  const bTotals = buckets.map(b=>[b, expRows.filter(r=>r.b===b).reduce((a,r)=>a+r.v,0)])
    .sort((a,b)=>b[1]-a[1]);
  document.getElementById("plTable").innerHTML =
    `<table class="tbl"><thead><tr><th>Expense group</th><th>Amount</th><th>% of expenses</th><th>% of revenue</th></tr></thead><tbody>`+
    bTotals.map(([b,v])=>`<tr><td>${esc(b)}</td><td>${fmtM(v)}</td>
      <td>${totExp?(v/totExp*100).toFixed(1):"0.0"}%</td>
      <td>${totRev?(v/totRev*100).toFixed(1):"0.0"}%</td></tr>`).join("")+
    `<tr class="tot"><td>Total</td><td>${fmtM(totExp)}</td><td>100%</td>
      <td>${totRev?(totExp/totRev*100).toFixed(1):"0.0"}%</td></tr></tbody></table>`;
}

/* ---------------- shared helpers ---------------- */
function group(rows, keyFn, valFn){
  const out={}; rows.forEach(r=>{ const k=keyFn(r); out[k]=(out[k]||0)+valFn(r); }); return out;
}
function sec(h, sub){ return `<div class="sec"><h3>${h}</h3>${sub?`<div class="sub">${sub}</div>`:""}</div>`; }
function esc(s){ return String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }

/* ---------------- main render ---------------- */
function render(){
  const w = scopeWindow();
  const ctx = renderKPIs(w);
  document.querySelectorAll(".panel").forEach(p=>p.classList.remove("on"));
  const el = document.getElementById("p-"+state.tab);
  el.classList.add("on");
  if (state.tab==="overview") renderOverview(el, w, ctx);
  else if (state.tab==="channels") renderChannels(el, w, ctx);
  else if (state.tab==="customers") renderCustomers(el, w, ctx);
  else if (state.tab==="shifts") renderShifts(el, w, ctx);
  else if (state.tab==="products") renderProducts(el, w);
  else if (state.tab==="pnl") renderPnl(el, w);
}

(async function(){
  try {
    await loadAll();
    buildFilters();
    render();
  } catch (e){
    document.querySelector("#loading .msg").textContent =
      "Failed to load data: " + e.message + " — try Refresh.";
    console.error(e);
    return;
  }
  document.getElementById("loading").style.display = "none";
})();
