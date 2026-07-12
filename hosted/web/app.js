/* Fyxx Executive Insights — hosted engine (exact port of app.py).
   Part 1: core + Brief, Exec Summary, Shifts, Pacing, Profitability, P&L.
   Timezone: Asia/Amman = UTC+3 fixed (no DST since 2022). */
"use strict";

const TZ_OFF = 3 * 3600;
const CURRENCY = "JOD";
const PAL = {
  bg:"#0A0A0B", surface:"#111114", surface2:"#16161B", border:"#23232B",
  border_lt:"#2D2D37", text:"#F4F4F5", dim:"#A1A1AA", muted:"#71717A",
  neon:"#19E3B6", neon_soft:"#0EA88B", amber:"#F5B544", rose:"#EC4899",
  violet:"#A78BFA", sky:"#38BDF8", good:"#22C55E", bad:"#F87171",
};
const CHANNEL_COLORS = {"E-com":"#19E3B6","Retail":"#38BDF8","TGR":"#A78BFA","B2B":"#F5B544","DF":"#EC4899"};
const COLORWAY = ["#19E3B6","#F5B544","#A78BFA","#38BDF8","#EC4899","#22C55E","#F87171","#FBBF24"];
const YEAR_COLORS = ["#38BDF8","#22C55E","#EC4899","#F5B544","#A78BFA","#19E3B6"];
const CH_ORDER = ["E-com","Retail","TGR","B2B","DF"];
const SHIFT_DAY = "Day · 10–17", SHIFT_EVE = "Evening · 17–01", SHIFT_OFF = "Off · 01–10";
const SHIFT_ORDER_L = [SHIFT_DAY, SHIFT_EVE, SHIFT_OFF];
const SHIFT_COLORS = {[SHIFT_DAY]:"#F5B544",[SHIFT_EVE]:"#A78BFA",[SHIFT_OFF]:"#3F3F46"};
const DONUT_SUPPLIER_HIGHLIGHT = ["UMG","Fyxx","Zumot","Arab Italian","YHC"];
const SUPPLIER_DONUT_COLORS = {"UMG":"#19E3B6","Fyxx":"#F5B544","Zumot":"#A78BFA",
  "Arab Italian":"#38BDF8","YHC":"#EC4899","Other":"#52525B"};
const DISPLAY_CAT_COLORS = {"Wines":"#A78BFA","Spirits":"#F5B544","Cocktails":"#EC4899",
  "Food":"#19E3B6","Cigars":"#F87171","Spirits BTG":"#38BDF8","Wine BTG":"#C4B5FD","Other":"#52525B"};
const CAT_SEQUENCE = ["Wines","Spirits","Cocktails","Food","Cigars","Spirits BTG","Wine BTG","Other"];

let D = {}, O = [], SS = [], DLV = [], LINES = null;
// Default scope = MTD (not Today): the hosted copy reads a periodic snapshot,
// so "Today" can legitimately be empty between syncs. MTD always has data.
let state = { scope:"MTD", channels:new Set(), allChannels:[],
              years:new Set(), allYears:[], custom:[null,null], tab:"brief" };

/* ================= time & format helpers ================= */
function local(ts){ return new Date((ts + TZ_OFF) * 1000); }
function dayKey(ts){ const d = local(ts);
  return d.getUTCFullYear()+"-"+String(d.getUTCMonth()+1).padStart(2,"0")+"-"+String(d.getUTCDate()).padStart(2,"0"); }
function todayLocal(){ const d = new Date(Date.now() + TZ_OFF*1000);
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate())); }
function nowLocalFrac(){ const d = new Date(Date.now() + TZ_OFF*1000);
  return (d.getUTCHours()*3600 + d.getUTCMinutes()*60 + d.getUTCSeconds()) / 86400; }
function dkOf(d){ return d.toISOString().slice(0,10); }
function addDays(d, n){ return new Date(d.getTime() + n*86400000); }
function parseDK(dk){ return new Date(dk + "T00:00:00Z"); }
function fmtDay(dk, opts){ return parseDK(dk).toLocaleDateString("en-GB",
  Object.assign({day:"2-digit",month:"short",timeZone:"UTC"}, opts||{})); }
function fmtDayFull(dk){ return parseDK(dk).toLocaleDateString("en-GB",
  {weekday:"long",day:"2-digit",month:"short",year:"numeric",timeZone:"UTC"}); }
function fmtDayShort(dk){ return parseDK(dk).toLocaleDateString("en-GB",
  {weekday:"short",day:"2-digit",month:"short",timeZone:"UTC"}); }
function monthOfDk(dk){ return dk.slice(0,7); }
function shiftOf(h){ if (h>=10 && h<17) return SHIFT_DAY; if (h>=17 || h<1) return SHIFT_EVE; return SHIFT_OFF; }

function fmtM(n, compact){
  if (n===null||n===undefined||isNaN(n)) return "—";
  if (compact){
    if (Math.abs(n)>=1e6) return (n/1e6).toFixed(2)+"M "+CURRENCY;
    if (Math.abs(n)>=1e3) return (n/1e3).toFixed(1)+"K "+CURRENCY;
  }
  return Math.round(n).toLocaleString("en-US")+" "+CURRENCY;
}
function fmtN(n){ return Math.round(n).toLocaleString("en-US"); }
function deltaPct(a,b){ return b ? (a-b)/b*100 : null; }
function deltaHtml(cur, prev, label){
  const p = deltaPct(cur, prev);
  if (p===null) return "<span style='color:#71717A'>no prior data</span>";
  const cls = p>=0?"kpi-delta-up":"kpi-delta-dn", ar = p>=0?"▲":"▼";
  return `<span class='${cls}'>${ar} ${Math.abs(p).toFixed(1)}%</span> <span style='color:#71717A'>${label||""}</span>`;
}
function deltaChip(cur, prev){
  if (!prev) return "<span class='delta flat'>· NEW</span>";
  const p = (cur-prev)/prev*100;
  return `<span class='delta ${p>=0?"up":"dn"}'>${p>=0?"▲":"▼"} ${Math.abs(p).toFixed(1)}%</span>`;
}
function esc(s){ return String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function ltr(s){ return "&#8206;"+esc(s); }
function median(xs){ if(!xs.length) return null; const s=[...xs].sort((a,b)=>a-b);
  const n=s.length; return n%2 ? s[(n-1)/2] : (s[n/2-1]+s[n/2])/2; }
function quantile(xs,q){ if(!xs.length) return null; const s=[...xs].sort((a,b)=>a-b);
  const pos=q*(s.length-1), lo=Math.floor(pos), hi=Math.ceil(pos);
  return s[lo]+(s[hi]-s[lo])*(pos-lo); }
function mean(xs){ return xs.length ? xs.reduce((a,b)=>a+b,0)/xs.length : 0; }
function std(xs){ if(xs.length<2) return 0; const m=mean(xs);
  return Math.sqrt(xs.reduce((a,x)=>a+(x-m)*(x-m),0)/(xs.length-1)); }
function groupSum(rows, keyFn, valFn){
  const out={}; rows.forEach(r=>{ const k=keyFn(r); out[k]=(out[k]||0)+valFn(r); }); return out;
}
function sortEntries(obj){ return Object.entries(obj).sort((a,b)=>b[1]-a[1]); }
function sec(h, sub, mt){ return `<div class='sec'${mt?` style='margin-top:${mt}px'`:""}><h3>${h}</h3>${sub?`<div class='sec-sub'>${sub}</div>`:""}</div>`; }

/* ================= sparkline / leaderboard / kpi (ports) ================= */
let _SPARK_N = 0;
function sparklineSvg(values, color){
  color = color || "#19E3B6";
  const vals = (values||[]).filter(v=>v!==null&&!isNaN(v)).map(Number);
  if (vals.length < 2) return "";
  const W=200,H=30, vmin=Math.min(...vals), vmax=Math.max(...vals);
  const span = vmax>vmin ? vmax-vmin : Math.max(Math.abs(vmax),1);
  const pts = vals.map((v,i)=>[ (i/(vals.length-1))*(W-4)+2, H-((v-vmin)/span)*(H-8)-4 ]);
  const line = "M"+pts.map(p=>p[0].toFixed(1)+","+p[1].toFixed(1)).join(" L");
  const fill = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)} `+
    pts.slice(1).map(p=>`L${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ")+
    ` L${pts[pts.length-1][0].toFixed(1)},${H-1} L${pts[0][0].toFixed(1)},${H-1} Z`;
  const id = "sk"+(++_SPARK_N);
  const [lx,ly] = pts[pts.length-1];
  return `<svg class='kpi-spark' viewBox='0 0 ${W} ${H}' preserveAspectRatio='none'>`+
    `<defs><linearGradient id='${id}' x1='0' x2='0' y1='0' y2='1'>`+
    `<stop offset='0%' stop-color='${color}' stop-opacity='0.30'/>`+
    `<stop offset='100%' stop-color='${color}' stop-opacity='0'/></linearGradient></defs>`+
    `<path d='${fill}' fill='url(#${id})'/>`+
    `<path d='${line}' stroke='${color}' stroke-width='1.6' fill='none' stroke-linecap='round' stroke-linejoin='round'/>`+
    `<circle cx='${lx.toFixed(1)}' cy='${ly.toFixed(1)}' r='2.2' fill='${color}'/></svg>`;
}
function kpiCard(label, value, sub, foot, spark, sparkColor){
  const fh = foot ? `<div class='kpi-foot'>${foot}</div>` : "";
  let sh = "";
  if (spark){ const svg = sparklineSvg(spark, sparkColor);
    if (svg) sh = `<div class='kpi-spark-row'>${svg}</div>`; }
  return `<div class='kpi'><div class='kpi-label'>${label}</div>`+
    `<div class='kpi-value'>${value}</div><div class='kpi-sub'>${sub||""}</div>${sh}${fh}</div>`;
}
function renderLeaderboard(rows, maxRows, color){
  maxRows = maxRows||10; color = color||"#19E3B6";
  if (!rows || !rows.length) return "<div class='lb-card'><div class='lb-empty'>No data</div></div>";
  rows = [...rows].sort((a,b)=>(b.value||0)-(a.value||0)).slice(0,maxRows);
  const maxVal = Math.max(...rows.map(r=>r.value||0), 1);
  const rankCls = ["lb-gold","lb-silver","lb-bronze"];
  let out = "<div class='lb-card'>";
  rows.forEach((r,i)=>{
    const cls = i<3 ? rankCls[i] : "";
    const sub = r.sub ? `<span class='lb-sub'>${esc(r.sub)}</span>` : "";
    let dh = "";
    if (r.delta_pct!==undefined && r.delta_pct!==null){
      dh = `<span class='lb-delta ${r.delta_pct>=0?"up":"dn"}'>${r.delta_pct>=0?"▲":"▼"} ${Math.abs(r.delta_pct).toFixed(1)}%</span>`;
    }
    out += `<div class='lb-row'><span class='lb-rank ${cls}'>${i+1}</span>`+
      `<div class='lb-body'><div class='lb-name'>${ltr(r.name||"—")}${sub}</div>`+
      `<div class='lb-bar'><div class='lb-bar-fill' style='width:${(r.value/maxVal*100).toFixed(1)}%;`+
      `background:linear-gradient(90deg, ${color} 0%, #38BDF8 100%);box-shadow:0 0 8px rgba(25,227,182,0.30)'></div></div></div>`+
      `<span class='lb-value'>${r.value_str||fmtN(r.value)}${dh}</span></div>`;
  });
  return out + "</div>";
}
/* Streamlit-ProgressColumn-style table cell */
function progCell(val, maxVal, fmt, color){
  const pct = maxVal ? Math.min(100, val/maxVal*100) : 0;
  return `<div class='prog-cell'><div class='prog-bg'><div class='prog-fill' `+
    `style='width:${pct.toFixed(1)}%;background:${color||PAL.neon}'></div></div>`+
    `<span class='prog-num'>${fmt}</span></div>`;
}
function dlCSV(filename, headerRow, rows){
  const q = s => `"${String(s??"").replace(/"/g,'""')}"`;
  const csv = [headerRow.map(q).join(",")]
    .concat(rows.map(r=>r.map(q).join(","))).join("\n");
  const blob = new Blob(["﻿"+csv], {type:"text/csv;charset=utf-8"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = filename; a.click();
  URL.revokeObjectURL(a.href);
}

/* ================= plotly helpers ================= */
const PCONF = {displayModeBar:false, responsive:true};
function baseLayout(h, legend, extra){
  return Object.assign({
    height:h, paper_bgcolor:PAL.surface, plot_bgcolor:PAL.surface,
    font:{family:"Inter, -apple-system, sans-serif", color:PAL.dim, size:11.5},
    colorway:COLORWAY, margin:{l:46,r:14,t:12,b:34},
    showlegend:!!legend,
    legend:{orientation:"h", y:-0.18, x:0, font:{size:11, color:PAL.dim}, bgcolor:"rgba(0,0,0,0)"},
    xaxis:{showgrid:false, tickfont:{size:10.5, color:PAL.muted}},
    yaxis:{gridcolor:"rgba(255,255,255,0.045)", griddash:"dot",
           tickfont:{size:10.5,color:PAL.muted}, zeroline:false},
    hoverlabel:{bgcolor:PAL.surface2, bordercolor:PAL.border_lt,
                font:{color:PAL.text, family:"Inter", size:12}},
  }, extra||{});
}
function plot(el, traces, layout){ const n=document.getElementById(el);
  if (n) Plotly.newPlot(n, traces, layout, PCONF); }

/* ================= data load ================= */
async function loadAll(){
  const names = ["meta","orders","sostates","delivery","lines","pnl"];
  const res = await Promise.all(names.map(n => fetch("data.php?f="+n).then(r=>{
    if(!r.ok) throw new Error(n+" HTTP "+r.status); return r.json(); })));
  names.forEach((n,i)=> D[n]=res[i]);

  const od = D.orders;
  O = od.ts.map((ts,i)=>{
    const l = local(ts), h = l.getUTCHours();
    return { ts, dk:dayKey(ts), mk:dayKey(ts).slice(0,7), y:l.getUTCFullYear(),
      m:l.getUTCMonth()+1, h, dow:(l.getUTCDay()+6)%7, shift:shiftOf(h),
      ch:od.channels[od.ch[i]], cu:od.customers[od.cu[i]],
      sp:od.salespeople[od.sp[i]], amt:od.amt[i], vat:od.vat[i],
      mg:od.mg[i], src:od.src[i], nm:od.nm?od.nm[i]:"",
      oid:od.oid?od.oid[i]:0, st:od.states?od.states[od.st[i]]:"sale" };
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
  LINES = D.lines;

  const chans = [...new Set(O.map(r=>r.ch))];
  chans.sort((a,b)=>{ const ia=CH_ORDER.indexOf(a), ib=CH_ORDER.indexOf(b);
    return (ia<0?99:ia)-(ib<0?99:ib) || a.localeCompare(b); });
  state.allChannels = chans;
  state.channels = new Set(chans);

  const cy = todayLocal().getUTCFullYear();
  state.allYears = [cy-2, cy-1, cy];
  state.years = new Set(state.allYears);

  document.getElementById("lastupd").innerHTML =
    "Synced <b style='color:#A1A1AA'>" + esc(D.meta.generated_at) + "</b> · Amman";
  document.getElementById("footer").innerHTML =
    `Fyxx Executive Insights · read-only · Odoo · data synced ${esc(D.meta.generated_at)} (Amman) · auto-refresh every 30 min`;
  const dt = todayLocal();
  document.getElementById("dFrom").value = dt.getUTCFullYear()+"-01-01";
  document.getElementById("dTo").value = dkOf(dt);
}

/* ================= scope + filters ================= */
function scopeWindow(){
  const t = todayLocal();
  const mainYear = state.years.size ? Math.max(...state.years) : t.getUTCFullYear();
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
    cs = new Date(Date.UTC(mainYear,0,1));
    ce = mainYear===t.getUTCFullYear() ? t : new Date(Date.UTC(mainYear,11,31));
    ps = new Date(Date.UTC(mainYear-1,0,1));
    pe = new Date(Date.UTC(mainYear-1, ce.getUTCMonth(), ce.getUTCDate()));
    label = "YTD "+mainYear;
  } else {
    cs = state.custom[0]?parseDK(state.custom[0]):new Date(Date.UTC(t.getUTCFullYear(),0,1));
    ce = state.custom[1]?parseDK(state.custom[1]):t;
    const span = Math.round((ce-cs)/86400000);
    pe = addDays(cs,-1); ps = addDays(pe,-span);
    label = dkOf(cs)+" → "+dkOf(ce);
  }
  return {cs:dkOf(cs), ce:dkOf(ce), ps:dkOf(ps), pe:dkOf(pe), label,
          days: Math.round((parseDK(dkOf(ce))-parseDK(dkOf(cs)))/86400000)+1};
}
function chOK(r){ return state.channels.has(r.ch); }
function dfAll(){ return O.filter(chOK); }                       // channel-filtered "df"
function inWin(r,a,b){ return r.dk>=a && r.dk<=b; }
function sliceWin(rows,a,b){ return rows.filter(r=>inWin(r,a,b)); }
function yearsWithData(df){
  return state.allYears.filter(y=>state.years.has(y) && df.some(r=>r.y===y)).sort();
}

/* ================= UI scaffolding ================= */
const SCOPES = ["Today","Yesterday","MTD","YTD","Custom"];
const TABS = [
  ["brief","◆ Brief"], ["exec","❖ Executive Summary"], ["shifts","◷ Online & Shifts"],
  ["pace","▲ Pacing"], ["profit","◯ Profitability"], ["pnl","Σ P&L"],
  ["sku","❒ Products"], ["loss","※ Loss Orders"], ["alerts","⚑ Alerts"],
  ["trends","⌁ Trends"], ["channels","⌬ Channels"], ["customers","◐ Customers"],
  ["cohorts","⟳ Cohorts"], ["compare","⇋ Compare"], ["live","● Live"],
];
function buildFilters(){
  const sp = document.getElementById("scopePills");
  sp.innerHTML = SCOPES.map(s=>`<button class="pillbtn ${s===state.scope?"on":""}" data-s="${s}">${s}</button>`).join("");
  sp.querySelectorAll(".pillbtn").forEach(b=>b.onclick=()=>{
    state.scope=b.dataset.s;
    document.getElementById("customDates").classList.toggle("show", state.scope==="Custom");
    buildFilters(); render(); });
  const cp = document.getElementById("chPills");
  cp.innerHTML = state.allChannels.map(c=>
    `<button class="pillbtn ${state.channels.has(c)?"on":""}" data-c="${c}">${c}</button>`).join("");
  cp.querySelectorAll(".pillbtn").forEach(b=>b.onclick=()=>{
    const c=b.dataset.c;
    if (state.channels.has(c)) state.channels.delete(c); else state.channels.add(c);
    if (!state.channels.size) state.allChannels.forEach(x=>state.channels.add(x));
    buildFilters(); render(); });
  // Years selector removed from the sidebar per request. state.years stays
  // pinned to all available years so the year-over-year charts still render
  // every year that has data.
  document.getElementById("customDates").classList.toggle("show", state.scope==="Custom");
  document.getElementById("dApply").onclick=()=>{
    state.custom=[document.getElementById("dFrom").value||null,
                  document.getElementById("dTo").value||null];
    render(); };
  const tb = document.getElementById("tabs");
  tb.innerHTML = TABS.map(([id,l])=>`<button class="tab ${id===state.tab?"on":""}" data-t="${id}">${l}</button>`).join("");
  tb.querySelectorAll(".tab").forEach(b=>b.onclick=()=>{ state.tab=b.dataset.t; buildFilters(); render(); });
}

/* ================= ticker + scope strip ================= */
function buildTicker(cur, prv, label){
  const items = [];
  const rev = cur.reduce((a,r)=>a+r.amt,0), prevRev = prv.reduce((a,r)=>a+r.amt,0);
  items.push(`<div class='ticker-item'><span class='label'>${label} · Total</span><span class='value'>${fmtM(rev,true)}</span>${deltaChip(rev,prevRev)}</div>`);
  items.push(`<div class='ticker-item'><span class='label'>Orders</span><span class='value'>${fmtN(cur.length)}</span>${deltaChip(cur.length,prv.length)}</div>`);
  const aov = cur.length?rev/cur.length:0, paov = prv.length?prevRev/prv.length:0;
  items.push(`<div class='ticker-item'><span class='label'>AOV</span><span class='value'>${fmtM(aov)}</span>${deltaChip(aov,paov)}</div>`);
  const cn = new Set(cur.map(r=>r.cu)).size, pn = new Set(prv.map(r=>r.cu)).size;
  items.push(`<div class='ticker-item'><span class='label'>Customers</span><span class='value'>${fmtN(cn)}</span>${deltaChip(cn,pn)}</div>`);
  if (cur.length){
    const chC = groupSum(cur, r=>r.ch, r=>r.amt), chP = groupSum(prv, r=>r.ch, r=>r.amt);
    sortEntries(chC).forEach(([c,v])=>{
      items.push(`<div class='ticker-item'><span class='label'>${esc(c)}</span><span class='value'>${fmtM(v,true)}</span>${deltaChip(v, chP[c]||0)}</div>`);
    });
    const cuR = sortEntries(groupSum(cur, r=>r.cu, r=>r.amt));
    if (cuR.length) items.push(`<div class='ticker-item'><span class='label'>Top Customer</span><span class='value'>${ltr(cuR[0][0])} · ${fmtM(cuR[0][1],true)}</span></div>`);
    const spR = sortEntries(groupSum(cur, r=>r.sp, r=>r.amt));
    if (spR.length) items.push(`<div class='ticker-item'><span class='label'>Top Sales</span><span class='value'>${ltr(spR[0][0])} · ${fmtM(spR[0][1],true)}</span></div>`);
    const bd = sortEntries(groupSum(cur, r=>r.dk, r=>r.amt));
    if (bd.length>1) items.push(`<div class='ticker-item'><span class='label'>Best Day</span><span class='value'>${fmtDay(bd[0][0])} · ${fmtM(bd[0][1],true)}</span></div>`);
  }
  const track = items.join("");
  document.getElementById("tickerSlot").innerHTML =
    `<div class='ticker-bar'><div class='ticker-live'><span class='dot'></span>Live</div>`+
    `<div class='ticker-mask'><div class='ticker-track'>${track}${track}</div></div></div>`;
}
function buildScopeStrip(w){
  const nCh = state.channels.size, nAll = state.allChannels.length;
  const chTxt = nCh<nAll ? `${nCh} of ${nAll} channels` : `all ${nAll} channels`;
  const now = new Date(Date.now()+TZ_OFF*1000);
  const hh = String(now.getUTCHours()).padStart(2,"0")+":"+String(now.getUTCMinutes()).padStart(2,"0")+":"+String(now.getUTCSeconds()).padStart(2,"0");
  document.getElementById("scopeStrip").innerHTML =
    `<div class='scope-strip'><span class='pill'>${esc(w.label)}</span>`+
    `<span class='dim'>·</span><span><b>${chTxt}</b></span>`+
    `<span class='dim'>·</span><span class='dim'>Updated ${hh} · Asia/Amman</span></div>`;
}

/* ================= KPI strip ================= */
function renderKPIs(w){
  const df = dfAll();
  const cur = sliceWin(df, w.cs, w.ce), prv = sliceWin(df, w.ps, w.pe);
  const S=a=>a.reduce((x,r)=>x+r.amt,0), V=a=>a.reduce((x,r)=>x+r.vat,0), M=a=>a.reduce((x,r)=>x+r.mg,0);
  const rev=S(cur), prev=S(prv), vat=V(cur), pvat=V(prv);
  const gross=rev+vat, pgross=prev+pvat;
  const profit=M(cur), pprofit=M(prv);
  const gm=rev?profit/rev*100:0, pgm=prev?pprofit/prev*100:0;
  const aov=cur.length?rev/cur.length:0, paov=prv.length?prev/prv.length:0;
  const custs=new Set(cur.map(r=>r.cu)).size, pcusts=new Set(prv.map(r=>r.cu)).size;

  // daily sparklines (2+ days only)
  let sRev=null,sGross=null,sGm=null,sOrders=null,sAov=null,sCust=null;
  const dks = [...new Set(cur.map(r=>r.dk))].sort();
  if (dks.length>1){
    const per = dks.map(dk=>{
      const dd = cur.filter(r=>r.dk===dk);
      const rv = dd.reduce((a,r)=>a+r.amt,0), vv = dd.reduce((a,r)=>a+r.vat,0),
            pf = dd.reduce((a,r)=>a+r.mg,0);
      return {rv, gross:rv+vv, gm:rv?pf/rv*100:0, n:dd.length,
              aov:dd.length?rv/dd.length:0, cust:new Set(dd.map(r=>r.cu)).size};
    });
    sRev=per.map(p=>p.rv); sGross=per.map(p=>p.gross); sGm=per.map(p=>p.gm);
    sOrders=per.map(p=>p.n); sAov=per.map(p=>p.aov); sCust=per.map(p=>p.cust);
  }
  const gmPpt = gm-pgm;
  const gmDelta = pgm ? `<span class='${gmPpt>=0?"kpi-delta-up":"kpi-delta-dn"}'>${gmPpt>=0?"▲":"▼"} ${Math.abs(gmPpt).toFixed(1)} ppt</span> <span style='color:#71717A'>vs prior period</span>`
                      : "<span style='color:#71717A'>no prior data</span>";
  document.getElementById("kpis").innerHTML =
    kpiCard("Net Amount", fmtM(rev,true), deltaHtml(rev,prev,"vs prior period"),
      "Prior: "+fmtM(prev,true), sRev, "#19E3B6")+
    kpiCard("Net Amount + VAT", fmtM(gross,true), deltaHtml(gross,pgross,"vs prior period"),
      "VAT: "+fmtM(vat,true)+(pgross?" · Prior gross: "+fmtM(pgross,true):""), sGross, "#5FF5CB")+
    kpiCard("Gross margin", gm.toFixed(1)+"%", gmDelta,
      "Profit: "+fmtM(profit,true)+(pgm?" · Prior: "+pgm.toFixed(1)+"%":""), sGm, "#F5B544")+
    kpiCard("Orders", fmtN(cur.length), deltaHtml(cur.length,prv.length,"vs prior period"),
      "Prior: "+fmtN(prv.length), sOrders, "#38BDF8")+
    kpiCard("Avg order value", cur.length?fmtM(aov):"—", deltaHtml(aov,paov,"vs prior period"),
      paov?"Prior: "+fmtM(paov):"", sAov, "#A78BFA")+
    kpiCard("Active customers", fmtN(custs), deltaHtml(custs,pcusts,"vs prior period"),
      "Prior: "+fmtN(pcusts), sCust, "#F5B544");
  return {cur, prv, rev, prev, vat, gross, profit, gm, pgm};
}

/* ================= TAB: Brief ================= */
function acc(v,color){ return `<b style='color:${color||"#19E3B6"}'>${v}</b>`; }
function signedPct(p){
  if (p===null||p===undefined) return "<span style='color:#71717A'>n/a</span>";
  const sign = p>=0?"+":"−", color = p>=0?"#22C55E":"#F87171";
  return `<b style='color:${color}'>${sign}${Math.abs(p).toFixed(1)}%</b>`;
}
function buildBrief(cur, prv, label){
  if (!cur.length)
    return `<p class='brief-lead'>No transactions were recorded in the <b>${esc(label)}</b> window for the selected channels. Try widening the period or re-enabling channels in the slicer above.</p>`;
  const rev = cur.reduce((a,r)=>a+r.amt,0), prev = prv.reduce((a,r)=>a+r.amt,0);
  const pct = prev?(rev-prev)/prev*100:null;
  const orders = cur.length, aov = orders?rev/orders:0;
  const customers = new Set(cur.map(r=>r.cu)).size;
  const prevOrders = prv.length, prevAov = prevOrders?prev/prevOrders:0;
  const prevCustomers = new Set(prv.map(r=>r.cu)).size;
  const chRev = sortEntries(groupSum(cur, r=>r.ch, r=>r.amt));
  const custRev = sortEntries(groupSum(cur, r=>r.cu, r=>r.amt));
  const spRev = sortEntries(groupSum(cur, r=>r.sp, r=>r.amt));
  const byDay = sortEntries(groupSum(cur, r=>r.dk, r=>r.amt));
  const chPrev = groupSum(prv, r=>r.ch, r=>r.amt);
  const chGrowth = chRev.filter(([c])=>chPrev[c]>0)
    .map(([c,r])=>[c,(r-chPrev[c])/chPrev[c]*100,r]).sort((a,b)=>b[1]-a[1]);
  let chCtx = "";
  if (state.channels.size < state.allChannels.length)
    chCtx = ` Filtered view: <b>${state.channels.size}</b> of ${state.allChannels.length} channels (${[...state.channels].join(", ")}).`;

  let pLead = `<p class='brief-lead'>During <b>${esc(label)}</b>, Fyxx generated ${acc(fmtM(rev,true))} in net revenue across ${acc(fmtN(orders))} transactions and ${acc(fmtN(customers))} active customers. `;
  if (pct!==null) pLead += `That puts the period ${signedPct(pct)} ${pct>=0?"ahead of":"behind"} the prior comparable window (${fmtM(prev,true)}). `;
  pLead += `Average order value sits at ${acc(fmtM(aov))}`;
  const aovPct = prevAov?(aov-prevAov)/prevAov*100:null;
  pLead += aovPct!==null ? `, ${signedPct(aovPct)} versus prior.` : ".";
  pLead += chCtx + "</p>";

  let pCh = "";
  if (chRev.length){
    const [tc,ta] = chRev[0];
    pCh = `<p><b>Channel mix.</b> ${acc(esc(tc))} continues to lead, contributing ${acc(fmtM(ta,true))} (${(rev?ta/rev*100:0).toFixed(1)}% of revenue). `;
    if (chRev.length>1){
      const [sc,sa] = chRev[1];
      pCh += `${acc(esc(sc))} follows at ${acc(fmtM(sa,true))} (${(rev?sa/rev*100:0).toFixed(1)}%). `;
    }
    if (chGrowth.length){
      const best = chGrowth[0], worst = chGrowth[chGrowth.length-1];
      if (best[1]>=0) pCh += `Fastest-growing channel: ${acc(esc(best[0]))} at ${signedPct(best[1])}. `;
      if (worst[1]<0 && worst[0]!==best[0]) pCh += `Underperforming: ${acc(esc(worst[0]),"#F87171")} at ${signedPct(worst[1])}. `;
    }
    pCh += "</p>";
  }

  const profitN = cur.reduce((a,r)=>a+r.mg,0);
  const prevProfitN = prv.reduce((a,r)=>a+r.mg,0);
  const gmPct = rev?profitN/rev*100:0, prevGmPct = prev?prevProfitN/prev*100:0;
  const chProf = {};
  cur.forEach(r=>{ const a=chProf[r.ch]=chProf[r.ch]||{rev:0,prof:0}; a.rev+=r.amt; a.prof+=r.mg; });
  const chProfArr = Object.entries(chProf).map(([c,a])=>({c, gm:a.rev?a.prof/a.rev*100:0, prof:a.prof}));
  const bestM = chProfArr.length ? chProfArr.reduce((a,b)=>a.gm>=b.gm?a:b) : null;
  const worstM = chProfArr.length>1 ? chProfArr.reduce((a,b)=>a.gm<=b.gm?a:b) : null;
  let pProfit = `<p><b>Profitability.</b> Gross profit was ${acc(fmtM(profitN,true))} on a margin of ${acc(gmPct.toFixed(1)+"%")}. `;
  if (prev && prevProfitN){
    const ppt = gmPct-prevGmPct, color = ppt>=0?"#22C55E":"#F87171";
    const ppc = prevProfitN?(profitN-prevProfitN)/prevProfitN*100:0;
    pProfit += `That's <span style='color:${color};font-weight:600'>${ppt>=0?"+":""}${ppt.toFixed(1)}ppt</span> versus the prior period (profit ${signedPct(ppc)}). `;
  }
  if (bestM) pProfit += `Strongest margin: ${acc(esc(bestM.c))} at ${acc(bestM.gm.toFixed(1)+"%")} delivering ${acc(fmtM(bestM.prof,true))} of profit. `;
  if (worstM && bestM && worstM.c!==bestM.c) pProfit += `Weakest: ${acc(esc(worstM.c),"#F87171")} at ${acc(worstM.gm.toFixed(1)+"%")}.`;
  pProfit += "</p>";

  let pCust = "<p>";
  if (custRev.length){
    const [tc,ta] = custRev[0];
    pCust += `<b>Demand concentration.</b> The single largest customer was ${acc(ltr(tc))} at ${acc(fmtM(ta,true))} (${(rev?ta/rev*100:0).toFixed(1)}% of period revenue). `;
    const top10 = custRev.slice(0,10).reduce((a,[,v])=>a+v,0);
    pCust += `The top 10 customers together account for ${acc((rev?top10/rev*100:0).toFixed(1)+"%")} of revenue. `;
  }
  if (customers && prevCustomers){
    pCust += `Active customer base moved ${signedPct((customers-prevCustomers)/prevCustomers*100)} versus the prior period.`;
  }
  pCust += "</p>";

  let pTeam = "";
  if (spRev.length){
    const [ts,ta] = spRev[0];
    pTeam = `<p><b>Sales team.</b> ${acc(ltr(ts))} led the team, attributed with ${acc(fmtM(ta,true))} (${(rev?ta/rev*100:0).toFixed(1)}% of period revenue) `;
    if (spRev.length>=3){
      const top3 = spRev.slice(0,3).reduce((a,[,v])=>a+v,0);
      pTeam += `and the top 3 salespeople drove ${acc((rev?top3/rev*100:0).toFixed(1)+"%")} of total revenue.`;
    } else pTeam = pTeam.trimEnd()+".";
    pTeam += "</p>";
  }

  let pDay = "";
  if (byDay.length>1){
    const [bd,bv] = byDay[0];
    const avg = byDay.reduce((a,[,v])=>a+v,0)/byDay.length;
    const ratio = avg?bv/avg:1;
    pDay = `<p><b>Standout day.</b> ${acc(fmtDayFull(bd))} delivered ${acc(fmtM(bv,true))}`;
    pDay += ratio>=1.5 ? ` — roughly ${ratio.toFixed(1)}× the daily average for the period.` : ".";
    pDay += "</p>";
  }

  let closing = "";
  if (pct!==null){
    if (pct>=10) closing = "<p class='brief-callout brief-good'>Net direction is clearly positive — momentum is on the upside. Recommended focus: protect the top-performing channel and double down on whatever drove the largest customers' purchases.</p>";
    else if (pct>=0) closing = "<p class='brief-callout brief-neutral'>Performance is broadly in line with the prior period. Watch the underperforming channels and customer concentration as leading indicators.</p>";
    else closing = "<p class='brief-callout brief-bad'>Performance trails the prior period. Recommended focus: identify which channels and customers slipped, and whether the gap is volume (orders) or value (AOV) driven.</p>";
  }
  return pLead+pCh+pProfit+pCust+pTeam+pDay+closing;
}
function renderBrief(el, w, ctx){
  const {cur, prv} = ctx;
  const lb = (curS, prvS)=>curS.slice(0,5).map(([name,val])=>{
    const row = {name, value:val, value_str:fmtM(val,true)};
    if (prvS[name]) row.delta_pct = (val-prvS[name])/prvS[name]*100;
    return row;
  });
  const chC = sortEntries(groupSum(cur, r=>r.ch, r=>r.amt)), chP = groupSum(prv, r=>r.ch, r=>r.amt);
  const cuC = sortEntries(groupSum(cur, r=>r.cu, r=>r.amt)), cuP = groupSum(prv, r=>r.cu, r=>r.amt);
  const spC = sortEntries(groupSum(cur, r=>r.sp, r=>r.amt)), spP = groupSum(prv, r=>r.sp, r=>r.amt);
  el.innerHTML =
    sec("Executive Brief", `Auto-generated narrative · ${esc(w.label)} · ${state.channels.size} channel(s)`)+
    `<div class='brief-card'>${buildBrief(cur, prv, w.label)}</div>`+
    (cur.length ? `<div class='grid3' style='margin-top:8px'>
      <div>${sec("Top channels","")}${renderLeaderboard(lb(chC,chP))}</div>
      <div>${sec("Top customers","")}${renderLeaderboard(lb(cuC,cuP))}</div>
      <div>${sec("Top salespeople","")}${renderLeaderboard(lb(spC,spP))}</div>
    </div>` : "");
}

/* ================= TAB: Executive Summary ================= */
function allowedPairSet(cur){
  const s = new Set();
  cur.forEach(r=>s.add(r.src+"|"+r.oid));
  return s;
}
function displayCat(sub, group){
  const s = (sub||"").trim().toLowerCase(), g = (group||"").trim().toLowerCase();
  if (s.includes("btg")) return s.includes("wine") ? "Wine BTG" : "Spirits BTG";
  if (s.includes("tasting card")) return "Wine BTG";
  if (s==="wine"||s==="wines") return "Wines";
  if (s==="spirits") return "Spirits";
  if (s.includes("cocktail")) return "Cocktails";
  if (s.includes("cigar")) return "Cigars";
  if (g==="food") return "Food";
  return "Other";
}
function linesFor(cur){
  const allowed = allowedPairSet(cur);
  const out = [];
  const L = LINES;
  for (let i=0;i<L.src.length;i++){
    if (allowed.has(L.src[i]+"|"+L.oid[i]))
      out.push({p:L.p[i], q:L.q[i], r:L.r[i], g:L.g[i], oid:L.oid[i], src:L.src[i]});
  }
  return out;
}
function renderExec(el, w, ctx){
  const {cur, rev, prev} = ctx;
  // insight chips
  let chips = "<div class='insights'>";
  if (cur.length){
    const chRev = sortEntries(groupSum(cur, r=>r.ch, r=>r.amt));
    if (chRev.length){
      const [tc,tv] = chRev[0];
      chips += `<div class='insight'><div class='ic'>★</div><div class='tx'><b>${esc(tc)}</b> leads with <b>${fmtM(tv,true)}</b> (${(rev?tv/rev*100:0).toFixed(1)}% of revenue).</div></div>`;
    }
    if (prev){
      const g = (rev-prev)/prev*100;
      chips += `<div class='insight'><div class='ic'>${g>=0?"▲":"▼"}</div><div class='tx'>Revenue is <b>${Math.abs(g).toFixed(1)}%</b> ${g>=0?"higher":"lower"} than the prior comparable period.</div></div>`;
    }
    const bd = sortEntries(groupSum(cur, r=>r.dk, r=>r.amt));
    if (bd.length) chips += `<div class='insight'><div class='ic'>◆</div><div class='tx'>Best single day: <b>${fmtDay(bd[0][0],{year:"numeric"})}</b> with <b>${fmtM(bd[0][1],true)}</b>.</div></div>`;
    const cu = sortEntries(groupSum(cur, r=>r.cu, r=>r.amt));
    if (cu.length) chips += `<div class='insight'><div class='ic'>♦</div><div class='tx'>Top customer: <b>${ltr(cu[0][0])}</b> — <b>${fmtM(cu[0][1],true)}</b>.</div></div>`;
  }
  chips += "</div>";

  el.innerHTML = chips +
    `<div class='grid32' style='margin-top:8px'>
      <div>${sec("Revenue trajectory · YTD by year","Cumulative net revenue, day-of-year basis")}
        <div class='card'><div id='exYtd'></div></div></div>
      <div>${sec("Revenue by product category", esc(w.label)+" · sub-category mix")}
        <div class='card'><div id='exCat'></div></div></div>
    </div>`+
    sec("Revenue by supplier", esc(w.label)+" · top suppliers by net revenue", 14)+
    `<div class='grid23'>
      <div><div class='card'><div id='exSup'></div></div></div>
      <div>${sec("Top 15 suppliers","All vendors, not just the donut highlights — drill into 'Other'")}
        <div class='card' style='padding:12px' id='exSupTbl'></div></div>
    </div>`;

  // YTD trajectory
  const df = dfAll();
  const yrs = yearsWithData(df);
  const t = todayLocal();
  const doy = d=>Math.floor((parseDK(d) - Date.UTC(parseDK(d).getUTCFullYear(),0,1))/86400000)+1;
  const traces = yrs.map((y,i)=>{
    const daily = {};
    df.filter(r=>r.y===y).forEach(r=>{ const dd=doy(r.dk); daily[dd]=(daily[dd]||0)+r.amt; });
    const xs = Object.keys(daily).map(Number).sort((a,b)=>a-b);
    const capDoy = y===t.getUTCFullYear() ? doy(dkOf(t)) : 366;
    let cum=0; const X=[],Y=[];
    xs.forEach(x=>{ if(x<=capDoy){ cum+=daily[x]; X.push(x); Y.push(Math.round(cum)); } });
    const color = y===t.getUTCFullYear() ? PAL.neon : YEAR_COLORS[i%YEAR_COLORS.length];
    const txt = X.map((_,j)=>j===X.length-1?fmtN(Y[Y.length-1]):"");
    return {x:X, y:Y, mode:"lines+text", name:String(y),
      line:{width:y===t.getUTCFullYear()?2.6:2, color}, text:txt,
      textposition:"top right", textfont:{color, size:11}, cliponaxis:false};
  });
  plot("exYtd", traces, Object.assign(baseLayout(340,true),{
    xaxis:{showgrid:false, tickfont:{size:10.5,color:PAL.muted},
      tickvals:[1,32,60,91,121,152,182,213,244,274,305,335],
      ticktext:["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]}}));

  // Category donut (order lines, channel-filtered via order membership)
  const ls = linesFor(cur);
  if (ls.length){
    const catRev = {};
    ls.forEach(l=>{ const p=LINES.products[l.p];
      const c = displayCat(p.c, p.g); catRev[c]=(catRev[c]||0)+l.r; });
    const cats = CAT_SEQUENCE.filter(c=>(catRev[c]||0)>0);
    const total = cats.reduce((a,c)=>a+catRev[c],0);
    plot("exCat", [{labels:cats, values:cats.map(c=>Math.round(catRev[c])),
      type:"pie", sort:false, direction:"clockwise", hole:.7,
      texttemplate:"%{value:,.0f}<br>%{percent}",
      marker:{colors:cats.map(c=>DISPLAY_CAT_COLORS[c]||"#52525B"),
              line:{color:PAL.surface,width:3}},
      textfont:{size:11,color:PAL.text}}],
      Object.assign(baseLayout(340,true),{annotations:[{
        text:`<b>${fmtM(total,true)}</b><br><span style='font-size:10px;color:#A1A1AA'>Categories</span>`,
        showarrow:false, font:{size:14,color:PAL.text}}]}));
    // Supplier donut + top15
    const supRev = {};
    ls.forEach(l=>{ const s=LINES.products[l.p].s||"No vendor tag";
      supRev[s]=(supRev[s]||0)+l.r; });
    const supFull = sortEntries(supRev);
    const donutAgg = {};
    supFull.forEach(([s,v])=>{ const k = DONUT_SUPPLIER_HIGHLIGHT.includes(s)?s:"Other";
      donutAgg[k]=(donutAgg[k]||0)+v; });
    const seq = [...DONUT_SUPPLIER_HIGHLIGHT,"Other"].filter(s=>(donutAgg[s]||0)>0);
    const supTotal = seq.reduce((a,s)=>a+donutAgg[s],0);
    plot("exSup", [{labels:seq, values:seq.map(s=>Math.round(donutAgg[s])),
      type:"pie", sort:false, direction:"clockwise", hole:.65,
      texttemplate:"%{value:,.0f}<br>%{percent}",
      marker:{colors:seq.map(s=>SUPPLIER_DONUT_COLORS[s]||"#52525B"),
              line:{color:PAL.surface,width:3}},
      textfont:{size:11,color:PAL.text}}],
      Object.assign(baseLayout(400,true),{annotations:[{
        text:`<b>${fmtM(supTotal,true)}</b><br><span style='font-size:10px;color:#A1A1AA'>${supFull.length} suppliers</span>`,
        showarrow:false, font:{size:14,color:PAL.text}}]}));
    const mx = supFull.length?supFull[0][1]:1;
    document.getElementById("exSupTbl").innerHTML =
      `<table class='tbl'><thead><tr><th>Supplier</th><th>Revenue (${CURRENCY})</th></tr></thead><tbody>`+
      supFull.slice(0,15).map(([s,v])=>`<tr><td>${ltr(s)}</td><td>${progCell(v,mx,fmtN(v))}</td></tr>`).join("")+
      `</tbody></table>`;
  } else {
    document.getElementById("exCat").innerHTML = "<div class='note' style='padding:20px'>No product line data for the active selection.</div>";
    document.getElementById("exSup").innerHTML = "<div class='note' style='padding:20px'>No product line data.</div>";
  }
}

/* ================= TAB: Pacing ================= */
function renderPacing(el, w){
  const df = dfAll();
  const t = todayLocal(); const tdk = dkOf(t);
  let paceStart, paceEnd, paceLabel, pctElapsed;
  if (state.scope==="Today"){
    paceStart=paceEnd=tdk; paceLabel="Today";
    pctElapsed = Math.min(1, nowLocalFrac());
  } else if (state.scope==="MTD"){
    const ms = new Date(Date.UTC(t.getUTCFullYear(), t.getUTCMonth(), 1));
    const nm = new Date(Date.UTC(t.getUTCFullYear(), t.getUTCMonth()+1, 1));
    paceStart=dkOf(ms); paceEnd=dkOf(addDays(nm,-1)); paceLabel="MTD";
    pctElapsed = (Math.round((t-ms)/86400000)+1)/(Math.round((addDays(nm,-1)-ms)/86400000)+1);
  } else if (state.scope==="YTD"){
    paceStart=t.getUTCFullYear()+"-01-01"; paceEnd=t.getUTCFullYear()+"-12-31";
    paceLabel="Year to Date";
    pctElapsed = (Math.round((t-parseDK(paceStart))/86400000)+1)/366;
  } else {
    paceStart=w.cs; paceEnd=w.ce; paceLabel=w.label;
    const total=Math.max(1, Math.round((parseDK(paceEnd)-parseDK(paceStart))/86400000)+1);
    const elapsed=Math.max(0, Math.min(total, Math.round((t-parseDK(paceStart))/86400000)+1));
    pctElapsed = elapsed/total;
  }
  pctElapsed = Math.max(0.001, Math.min(1, pctElapsed));
  const span = Math.round((parseDK(paceEnd)-parseDK(paceStart))/86400000)+1;
  const paceRev = sliceWin(df, paceStart, paceEnd).reduce((a,r)=>a+r.amt,0);
  const priorTotals = [];
  for (let i=1;i<=3;i++){
    const ps = dkOf(addDays(parseDK(paceStart), -span*i));
    const pe = dkOf(addDays(parseDK(ps), span-1));
    const v = sliceWin(df, ps, pe).reduce((a,r)=>a+r.amt,0);
    if (v>0) priorTotals.push(v);
  }
  const baseline = priorTotals.length ? mean(priorTotals) : 0;
  const forecast = pctElapsed>0 ? paceRev/pctElapsed : paceRev;
  const pacePct = baseline ? paceRev/(baseline*pctElapsed)*100 : null;

  el.innerHTML =
    sec("Pacing & forecast", `${esc(paceLabel)} · ${fmtDay(paceStart)} → ${fmtDay(paceEnd,{year:"numeric"})} · ${(pctElapsed*100).toFixed(0)}% elapsed`)+
    `<div class='grid23'>
      <div><div class='card'><div id='paceGauge'></div></div></div>
      <div><div class='kpi-grid' style='gap:10px' id='paceKpis'></div></div>
    </div>`+
    sec("Cumulative this period vs prior","Day-by-day cumulative revenue, this cycle (neon) vs each of the prior 3 equivalent cycles",18)+
    `<div class='card'><div id='paceCum'></div></div>`+
    sec("7-day momentum","Rolling 7-day revenue · last 60 days",14)+
    `<div class='card'><div id='paceMom'></div></div>`;

  const gaugeMax = Math.max(baseline*1.4, forecast*1.1, paceRev*1.1, 1);
  plot("paceGauge", [{type:"indicator", mode:"gauge+number", value:paceRev,
    number:{valueformat:",.0f", font:{size:30,color:PAL.text}},
    title:{text:`<span style='color:#A1A1AA;font-size:11px'>${esc(paceLabel)} · current</span>`, font:{size:12}},
    gauge:{axis:{range:[0,gaugeMax], tickfont:{color:PAL.muted,size:9}},
      bar:{color:PAL.neon, thickness:.28}, bgcolor:"#0E0E12", borderwidth:0,
      steps:[{range:[0, baseline?baseline*.6:gaugeMax*.4], color:"rgba(248,113,113,0.10)"},
             {range:[baseline?baseline*.6:gaugeMax*.4, baseline||gaugeMax*.7], color:"rgba(245,181,68,0.10)"},
             {range:[baseline||gaugeMax*.7, gaugeMax], color:"rgba(34,197,94,0.10)"}],
      threshold:{line:{color:PAL.violet,width:3}, thickness:.85,
                 value:baseline?baseline*pctElapsed:0}}}],
    {height:280, margin:{l:0,r:0,t:30,b:0}, paper_bgcolor:PAL.surface,
     font:{family:"Inter, sans-serif"}});

  let status;
  if (pacePct!==null){
    status = pacePct>=105 ? ["Ahead of pace","kpi-delta-up","▲"]
           : pacePct>=95 ? ["On pace","","●"] : ["Behind pace","kpi-delta-dn","▼"];
  } else status = ["No prior baseline","",""];
  let kh = "";
  kh += kpiCard("Forecast end-of-period", fmtM(forecast,true),
    `At current run-rate of ${fmtM(pctElapsed?paceRev/pctElapsed:0)} per period unit`,
    baseline?`Baseline (avg of prior 3): ${fmtM(baseline,true)}`:"");
  kh += kpiCard("Pacing status",
    status[2]?`<span class='${status[1]}'>${status[2]} ${status[0]}</span>`:status[0],
    pacePct!==null?`${pacePct.toFixed(1)}% of the pro-rated baseline`:"",
    `Pro-rated target: ${fmtM(baseline?baseline*pctElapsed:0,true)}`);
  const daysLeft = Math.max(0, Math.round((parseDK(paceEnd)-t)/86400000));
  if (daysLeft>0 && baseline){
    kh += kpiCard("Required daily run-rate", fmtM(Math.max(0,(baseline-paceRev)/daysLeft),true),
      `To match baseline by period end · ${daysLeft} days remaining`, "");
  } else {
    kh += kpiCard("Days remaining", fmtN(daysLeft), daysLeft===0?"Period ends today":"", "");
  }
  if (baseline){
    const fd = (forecast-baseline)/baseline*100;
    kh += kpiCard("Forecast vs baseline",
      `<span class='${fd>=0?"kpi-delta-up":"kpi-delta-dn"}'>${fd>=0?"▲":"▼"} ${Math.abs(fd).toFixed(1)}%</span>`,
      fmtM(forecast-baseline,true)+" absolute", "");
  }
  document.getElementById("paceKpis").innerHTML = kh;

  // cumulative chart
  if (baseline){
    const traces = [];
    for (let i=3;i>=1;i--){
      const ps = addDays(parseDK(paceStart), -span*i);
      const pe = addDays(ps, span-1);
      const rows = sliceWin(df, dkOf(ps), dkOf(pe));
      if (!rows.length) continue;
      const per = {};
      rows.forEach(r=>{ const off=Math.round((parseDK(r.dk)-ps)/86400000); per[off]=(per[off]||0)+r.amt; });
      let cum=0; const Y=[];
      for (let j=0;j<span;j++){ cum += per[j]||0; Y.push(Math.round(cum)); }
      traces.push({x:[...Array(span).keys()], y:Y, mode:"lines",
        name:`${fmtDay(dkOf(ps))} → ${fmtDay(dkOf(pe))}`,
        line:{width:1.5,color:"#52525B",dash:"dot"}, opacity:.6});
    }
    const rowsC = sliceWin(df, paceStart, paceEnd);
    if (rowsC.length){
      const per = {};
      rowsC.forEach(r=>{ const off=Math.round((parseDK(r.dk)-parseDK(paceStart))/86400000); per[off]=(per[off]||0)+r.amt; });
      const offs = Object.keys(per).map(Number).sort((a,b)=>a-b);
      let cum=0; const X=[],Y=[];
      offs.forEach(o=>{ cum+=per[o]; X.push(o); Y.push(Math.round(cum)); });
      traces.push({x:X, y:Y, mode:"lines+markers", name:"This cycle",
        line:{width:3,color:PAL.neon}, marker:{size:5,color:PAL.neon}});
      if (pctElapsed<1 && X.length){
        const lastDay = X[X.length-1], lastVal = Y[Y.length-1];
        const rate = lastDay>=0 ? lastVal/(lastDay+1) : 0;
        const px=[], py=[];
        for (let j=lastDay;j<span;j++){ px.push(j); py.push(Math.round(lastVal+rate*(j-lastDay))); }
        traces.push({x:px, y:py, mode:"lines", name:"Forecast",
          line:{width:2,color:PAL.neon,dash:"dash"}, opacity:.6});
      }
    }
    plot("paceCum", traces, Object.assign(baseLayout(360,true),
      {xaxis:{title:{text:"Day of period",font:{size:11,color:PAL.muted}},
              showgrid:false, tickfont:{size:10.5,color:PAL.muted}}}));
  } else {
    document.getElementById("paceCum").innerHTML =
      "<div class='note' style='padding:18px'>Need at least one prior equivalent period for baseline comparison.</div>";
  }
  // 7-day momentum
  const cutoff = dkOf(addDays(t,-59));
  const d60 = df.filter(r=>r.dk>=cutoff);
  if (d60.length){
    const daily = groupSum(d60, r=>r.dk, r=>r.amt);
    const dks = Object.keys(daily).sort();
    const vals = dks.map(k=>daily[k]);
    const roll = vals.map((_,i)=>{ const s=vals.slice(Math.max(0,i-6),i+1); return mean(s); });
    plot("paceMom", [
      {x:dks, y:vals.map(Math.round), name:"Daily", type:"bar",
       marker:{color:"#23232B"}},
      {x:dks, y:roll.map(Math.round), name:"7-day avg", mode:"lines",
       line:{width:2.5,color:PAL.neon,shape:"spline"}},
    ], baseLayout(300,true));
  }
}

/* ================= TAB: Profitability ================= */
function renderProfit(el, w, ctx){
  const {cur, prv} = ctx;
  el.innerHTML = sec("Profitability", esc(w.label)+" · gross profit and margin %, from Odoo's per-order margin field (real cost data)");
  if (!cur.length){ el.innerHTML += "<div class='note'>No data in selected window.</div>"; return; }
  const revP = cur.reduce((a,r)=>a+r.amt,0), profitP = cur.reduce((a,r)=>a+r.mg,0);
  const marginPct = revP?profitP/revP*100:0, cogsP = revP-profitP;
  const prevRevP = prv.reduce((a,r)=>a+r.amt,0), prevProfitP = prv.reduce((a,r)=>a+r.mg,0);
  const prevMarginPct = prevRevP?prevProfitP/prevRevP*100:0;
  const chG = {};
  cur.forEach(r=>{ const a=chG[r.ch]=chG[r.ch]||{rev:0,prof:0,n:0}; a.rev+=r.amt; a.prof+=r.mg; a.n++; });
  const chArr = Object.entries(chG).map(([c,a])=>({c,...a, gm:a.rev?a.prof/a.rev*100:0}))
    .sort((a,b)=>b.prof-a.prof);
  let kh = "";
  kh += kpiCard("Gross profit", fmtM(profitP,true), deltaHtml(profitP,prevProfitP,"vs prior period"),
    "Prior: "+fmtM(prevProfitP,true));
  kh += kpiCard("Gross margin", marginPct.toFixed(1)+"%",
    prevMarginPct?deltaHtml(marginPct,prevMarginPct,"ppts vs prior"):"<span style='color:#71717A'>no prior</span>",
    prevMarginPct?"Prior: "+prevMarginPct.toFixed(1)+"%":"");
  kh += kpiCard("COGS", fmtM(cogsP,true),
    `<span style='color:#71717A'>${(revP?cogsP/revP*100:0).toFixed(1)}% of revenue</span>`, "");
  if (chArr.length){
    const best = [...chArr].sort((a,b)=>b.gm-a.gm)[0];
    kh += kpiCard("Highest-margin channel", `<span style='color:#19E3B6'>${esc(best.c)}</span>`,
      `<b>${best.gm.toFixed(1)}%</b> margin · ${fmtM(best.prof,true)} profit`, "");
  }
  el.innerHTML +=
    `<div class='kpi-grid'>${kh}</div>`+
    `<div class='grid32' style='margin-top:14px'>
      <div>${sec("Profit and margin by channel", esc(w.label))}
        <div class='card'><div id='prByCh'></div></div></div>
      <div>${sec("Revenue split","Gross profit vs cost of goods")}
        <div class='card'><div id='prSplit'></div></div></div>
    </div>`+
    sec("Channel profitability detail","",14)+
    `<div class='card' style='padding:12px' id='prTbl'></div>`+
    `<div class='grid2' style='margin-top:14px'>
      <div>${sec("Top customers by profit","")}<div id='prCust'></div></div>
      <div>${sec("Top salespeople by profit","")}<div id='prSp'></div></div>
    </div>`;
  const sorted = [...chArr].sort((a,b)=>a.prof-b.prof);
  plot("prByCh", [{y:sorted.map(x=>x.c), x:sorted.map(x=>Math.round(x.prof)),
    type:"bar", orientation:"h",
    marker:{color:sorted.map(x=>CHANNEL_COLORS[x.c]||PAL.neon)},
    text:sorted.map(x=>`${fmtN(x.prof)}  (${x.gm.toFixed(1)}%)`),
    textposition:"outside", textfont:{color:PAL.dim,size:11}, cliponaxis:false}],
    baseLayout(380,false));
  plot("prSplit", [{labels:["Gross profit","COGS"],
    values:[Math.max(profitP,0),Math.max(cogsP,0)], type:"pie", hole:.7,
    texttemplate:"%{value:,.0f}<br>%{percent}",
    marker:{colors:["#19E3B6","#3F3F46"], line:{color:PAL.surface,width:3}},
    textfont:{size:12,color:PAL.text}}],
    Object.assign(baseLayout(380,true),{annotations:[{
      text:`<b>${marginPct.toFixed(1)}%</b><br><span style='font-size:10px;color:#A1A1AA'>Margin</span>`,
      showarrow:false, font:{size:14,color:PAL.text}}]}));
  const mxR = Math.max(...chArr.map(x=>x.rev),1), mxP = Math.max(...chArr.map(x=>x.prof),1);
  document.getElementById("prTbl").innerHTML =
    `<table class='tbl'><thead><tr><th>Channel</th><th>Orders</th><th>Revenue (${CURRENCY})</th>
     <th>Profit (${CURRENCY})</th><th>Margin %</th><th>% of revenue</th><th>% of profit</th></tr></thead><tbody>`+
    chArr.map(x=>`<tr><td><span style='color:${CHANNEL_COLORS[x.c]||PAL.text}'>●</span> ${esc(x.c)}</td>
      <td>${fmtN(x.n)}</td><td>${progCell(x.rev,mxR,fmtN(x.rev))}</td>
      <td>${progCell(Math.max(x.prof,0),mxP,fmtN(x.prof))}</td>
      <td>${progCell(x.gm,100,x.gm.toFixed(1)+"%",PAL.amber)}</td>
      <td>${progCell(revP?x.rev/revP*100:0,100,(revP?x.rev/revP*100:0).toFixed(1)+"%",PAL.sky)}</td>
      <td>${progCell(profitP?Math.max(x.prof/profitP*100,0):0,100,(profitP?x.prof/profitP*100:0).toFixed(1)+"%",PAL.violet)}</td></tr>`).join("")+
    `</tbody></table>`;
  const mkLb = key=>{
    const g = {};
    cur.forEach(r=>{ const a=g[r[key]]=g[r[key]]||{rev:0,prof:0}; a.rev+=r.amt; a.prof+=r.mg; });
    return Object.entries(g).map(([name,a])=>({name,
      sub:`${(a.rev?a.prof/a.rev*100:0).toFixed(1)}% margin`,
      value:a.prof, value_str:fmtM(a.prof,true)}))
      .sort((a,b)=>b.value-a.value).slice(0,10);
  };
  document.getElementById("prCust").innerHTML = renderLeaderboard(mkLb("cu"));
  document.getElementById("prSp").innerHTML = renderLeaderboard(mkLb("sp"));
}

/* ================= TAB: P&L ================= */
function pnlCategoryOf(name){
  const n = (name||"").toLowerCase();
  const parent = n.split(":")[0].trim();
  if (!parent) return name||"Other";
  return parent.replace(/\b\w/g, c=>c.toUpperCase());
}
function pnlBalances(a, b){
  // per-account balance within [a..b] from D.pnl rows (day, accIdx, amount)
  const out = new Array(D.pnl.accounts.length).fill(0);
  D.pnl.rows.forEach(([d, ai, v])=>{ if (d>=a && d<=b) out[ai]+=v; });
  return out;
}
function renderPnl(el, w, ctx){
  const {cur, prv} = ctx;
  const rev = cur.reduce((a,r)=>a+r.amt,0), prevRev = prv.reduce((a,r)=>a+r.amt,0);
  const gp = cur.reduce((a,r)=>a+r.mg,0), prevGp = prv.reduce((a,r)=>a+r.mg,0);
  const cogs = rev-gp, prevCogs = prevRev-prevGp;
  const balC = pnlBalances(w.cs, w.ce), balP = pnlBalances(w.ps, w.pe);
  const A = D.pnl.accounts;
  const isCogsAcc = n=>{ const s=(n||"").toLowerCase(); return s.includes("cost of goods sold")||s.includes("cogs"); };
  const groupOpex = bal=>{
    const g = {};
    A.forEach((a,i)=>{
      if (isCogsAcc(a.name) || a.type==="expense_direct_cost") return;
      if (Math.abs(bal[i])<0.01) return;
      const c = pnlCategoryOf(a.name);
      g[c]=(g[c]||0)+bal[i];
    });
    return g;
  };
  const depTotal = bal=>A.reduce((s,a,i)=>s + (a.type==="expense_depreciation"&&Math.abs(bal[i])>0.01 ? bal[i] : 0), 0);
  const opexC = groupOpex(balC), opexP = groupOpex(balP);
  const depC = depTotal(balC), depP = depTotal(balP);
  const totOpexC = Object.values(opexC).reduce((a,b)=>a+b,0);
  const totOpexP = Object.values(opexP).reduce((a,b)=>a+b,0);
  const ebitdaC = gp-totOpexC, ebitdaP = prevGp-totOpexP;
  const ebitC = ebitdaC-depC, ebitP = ebitdaP-depP;
  const fmtD = (c,p)=>{ const d=deltaPct(c,p);
    if (d===null) return "<span style='color:#71717A'>—</span>";
    return `<span class='${d>=0?"kpi-delta-up":"kpi-delta-dn"}'>${d>=0?"▲":"▼"} ${Math.abs(d).toFixed(1)}%</span>`; };
  const row = (label, c, p, opt)=>{
    opt = opt||{};
    const neg = opt.neg?"pnl-neg":"";
    const lc = opt.sub?"pnl-sub-label":"pnl-row-label";
    const cs = opt.neg?`(${fmtN(Math.abs(c))})`:fmtN(c);
    const ps = opt.neg?`(${fmtN(Math.abs(p))})`:fmtN(p);
    return `<tr class='${opt.cls||""}'><td class='${lc}'>${esc(label)}</td>`+
      `<td class='${neg}'>${cs}</td><td class='${neg}'>${ps}</td><td>${(p||c)?fmtD(c,p):"—"}</td></tr>`;
  };
  let t = `<table class='pnl-table'><thead><tr><th>Line Item</th>`+
    `<th>${esc(w.label)} (${CURRENCY})</th><th>Prior period (${CURRENCY})</th><th>Δ %</th></tr></thead><tbody>`;
  t += row("Revenue (net of VAT)", rev, prevRev, {cls:"pnl-total"});
  t += row("Cost of Goods Sold", cogs, prevCogs, {neg:true});
  t += row("Gross Profit", gp, prevGp, {cls:"pnl-total"});
  const gmC = rev?gp/rev*100:0, gmP = prevRev?prevGp/prevRev*100:0, ppt = gmC-gmP;
  t += `<tr><td class='pnl-sub-label'><i>Gross Margin %</i></td><td><i>${gmC.toFixed(1)}%</i></td>`+
    `<td><i>${gmP.toFixed(1)}%</i></td><td>${prevRev?`<span class='${ppt>=0?"kpi-delta-up":"kpi-delta-dn"}'>${ppt>=0?"▲":"▼"} ${Math.abs(ppt).toFixed(1)} ppt</span>`:"<span style='color:#71717A'>—</span>"}</td></tr>`;
  t += "<tr><td colspan='4' style='height:8px;background:#0E0E13;border-bottom:1px solid #2A2A33'></td></tr>";
  t += "<tr><td class='pnl-row-label' style='color:#A78BFA;text-transform:uppercase;letter-spacing:0.10em;font-size:11px;font-weight:700' colspan='4'>Operating Expenses</td></tr>";
  const cats = [...new Set([...Object.keys(opexC),...Object.keys(opexP)])]
    .sort((a,b)=>Math.abs(opexC[b]||0)-Math.abs(opexC[a]||0));
  if (!cats.length)
    t += "<tr><td colspan='4' class='pnl-sub-label' style='color:#71717A'><i>No operating expenses posted to Odoo for this period.</i></td></tr>";
  cats.forEach(c=>{ t += row(c, opexC[c]||0, opexP[c]||0, {neg:true, sub:true}); });
  t += row("Total OpEx", totOpexC, totOpexP, {neg:true, cls:"pnl-total"});
  t += row("EBITDA", ebitdaC, ebitdaP, {cls:"pnl-total"});
  if (Math.abs(depC)>0.01 || Math.abs(depP)>0.01)
    t += row("Depreciation & Amortisation", depC, depP, {neg:true, sub:true});
  t += row("EBIT (Operating Income)", ebitC, ebitP, {cls:"pnl-bottom"});
  t += "</tbody></table>";

  el.innerHTML =
    sec("Profit &amp; Loss Statement", esc(w.label)+" · live from Odoo GL · OpEx figures reflect everything posted to expense accounts company-wide")+
    "<div class='note'>Revenue, COGS, and Gross Profit are channel-filtered. OpEx categories are <b>company-wide</b> (not channel-attributable). Lines with zero balance are hidden.</div>"+
    t +
    sec("Operating expenses · breakdown","Posted to Odoo this period — top categories",18)+
    `<div class='card'><div id='plOpex'></div></div>`+
    sec("Detailed account ledger","Every expense account with a non-zero balance",18)+
    `<div class='card' style='padding:12px' id='plLedger'></div>`;

  const items = sortEntries(opexC);
  if (items.length){
    plot("plOpex", [{x:items.map(x=>Math.round(x[1])).reverse(),
      y:items.map(x=>x[0]).reverse(), type:"bar", orientation:"h",
      marker:{color:items.map(x=>x[1]).reverse(),
              colorscale:[[0,"#0E5A4A"],[1,"#F87171"]]},
      text:items.map(x=>fmtN(x[1])).reverse(), textposition:"outside",
      textfont:{color:PAL.dim,size:10}, cliponaxis:false}],
      baseLayout(Math.max(300, items.length*26+80), false));
  } else document.getElementById("plOpex").innerHTML = "<div class='note' style='padding:16px'>No OpEx posted for this period.</div>";
  const detail = A.map((a,i)=>({code:a.code, name:a.name, type:a.type,
    cur:balC[i], prev:balP[i]})).filter(d=>Math.abs(d.cur)>=0.01)
    .sort((a,b)=>b.cur-a.cur);
  if (detail.length){
    const mx = Math.max(...detail.map(d=>d.cur),1);
    document.getElementById("plLedger").innerHTML =
      `<div style='max-height:420px;overflow:auto'><table class='tbl'><thead><tr><th>Code</th><th>Account</th><th>Type</th>
       <th>Period (${CURRENCY})</th><th>Prior (${CURRENCY})</th><th>Δ %</th></tr></thead><tbody>`+
      detail.map(d=>{ const dp = deltaPct(d.cur, d.prev);
        return `<tr><td>${esc(d.code)}</td><td>${esc(d.name)}</td><td>${esc(d.type)}</td>
        <td>${progCell(Math.max(d.cur,0),mx,fmtN(d.cur))}</td><td>${fmtN(d.prev)}</td>
        <td>${dp===null?"—":dp.toFixed(1)+"%"}</td></tr>`; }).join("")+
      `</tbody></table></div>`;
  } else document.getElementById("plLedger").innerHTML =
      "<div class='note'>Every expense account is at zero for this period.</div>";
}

/* ================= main render ================= */
function render(){
  const w = scopeWindow();
  const ctx = renderKPIs(w);
  buildTicker(ctx.cur, ctx.prv, w.label);
  buildScopeStrip(w);
  document.querySelectorAll(".panel").forEach(p=>p.classList.remove("on"));
  const el = document.getElementById("p-"+state.tab);
  el.classList.add("on");
  const R = {
    brief:renderBrief, exec:renderExec, shifts:window.renderShifts,
    pace:renderPacing, profit:renderProfit, pnl:renderPnl,
    sku:window.renderSku, loss:window.renderLoss, alerts:window.renderAlerts,
    trends:window.renderTrends, channels:window.renderChannels2,
    customers:window.renderCustomers2, cohorts:window.renderCohorts,
    compare:window.renderCompare, live:window.renderLive,
  };
  const fn = R[state.tab];
  if (fn) fn(el, w, ctx);
}

(async function(){
  try {
    await loadAll();
    buildFilters();
    render();
  } catch (e){
    const m = document.querySelector("#loading .msg");
    if (m) m.textContent = "Failed to load data: " + e.message + " — try Refresh.";
    console.error(e);
    return;
  }
  document.getElementById("loading").style.display = "none";
})();
