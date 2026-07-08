/* Fyxx Executive Insights — hosted engine, part 2.
   Tabs: Online & Shifts (+delivery+fleet), Products, Loss Orders, Alerts,
   Trends, Channels, Customers, Cohorts, Compare, Live. */
"use strict";

/* ================= TAB: Online & Shifts ================= */
window.renderShifts = function(el, w, ctx){
  const cur = ctx.cur.map(r=>r), prv = ctx.prv;
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
  const byDay = groupSum(cur, r=>r.dk, ()=>1);
  const busiest = sortEntries(byDay)[0];
  const chNote = state.channels.size===state.allChannels.length ? "all channels"
                : [...state.channels].join(", ");

  const ins = [];
  if (cur.length){
    const dom = nEve>=nDay ? ["evening",nEve,nDay] : ["day",nDay,nEve];
    ins.push(`The <b>${dom[0]} shift</b> drives <b>${(dom[1]/cur.length*100).toFixed(0)}%</b> of ${noun} this period — <b>${fmtN(dom[1])}</b> vs <b>${fmtN(dom[2])}</b> on the other shift.`);
    const byH = groupSum(cur, r=>r.h, ()=>1);
    const pk = sortEntries(byH)[0];
    if (pk){ const h=+pk[0];
      ins.push(`Peak hour is <b>${String(h).padStart(2,"0")}:00</b> with <b>${fmtN(pk[1])}</b> orders — concentrate staffing around the ${(h>=17||h<1)?"evening":"afternoon"} rush.`); }
    if (prv.length){ const d=(cur.length-prv.length)/prv.length*100;
      ins.push(`Volume is <b>${d>=0?"up":"down"} ${Math.abs(d).toFixed(0)}%</b> vs the prior period (${fmtN(cur.length)} vs ${fmtN(prv.length)}).`); }
    if (busiest){
      const qd = sortEntries(byDay).slice(-1)[0];
      ins.push(`Busiest day <b>${fmtDayShort(busiest[0])}</b> (${fmtN(busiest[1])}); quietest <b>${fmtDayShort(qd[0])}</b> (${fmtN(qd[1])}).`); }
    const placed = cur.length + cancels.length;
    if (placed) ins.push(`<b>${fmtN(cancels.length)}</b> orders were cancelled this period — <b>${(cancels.length/placed*100).toFixed(0)}%</b> of all placed.`);
    if (nOff) ins.push(`<b>${fmtN(nOff)}</b> orders landed off-shift (01:00–10:00).`);
    ins.push(drafts.length ? `<b>${fmtN(drafts.length)}</b> draft quotation(s) pending in Odoo.` : "No draft quotations are currently pending in Odoo.");
  } else ins.push(`No ${noun} matched the current filters in this period.`);

  el.innerHTML =
    sec((isOnline?"Online Orders &amp; Shift Analytics":"Orders &amp; Shift Analytics"),
      `${esc(w.label)} · ${fmtDay(w.cs)} → ${fmtDay(w.ce,{year:"numeric"})} (${w.days} days) · Day 10:00–17:00 · Evening 17:00–01:00 · channels: ${esc(chNote)}`)+
    `<div class='kpi-grid' style='margin-top:6px'>`+
    kpiCard("Orders · period", fmtN(cur.length), deltaHtml(cur.length,prv.length,"vs prior period"), "Prior: "+fmtN(prv.length))+
    kpiCard("Day shift · 10–17", fmtN(nDay), deltaHtml(nDay,pDay,"vs prior period"), (cur.length?(nDay/cur.length*100).toFixed(0):0)+"% of orders")+
    kpiCard("Evening shift · 17–01", fmtN(nEve), deltaHtml(nEve,pEve,"vs prior period"), (cur.length?(nEve/cur.length*100).toFixed(0):0)+"% of orders")+
    kpiCard("Busiest day", busiest?fmtDayShort(busiest[0]):"—", busiest?fmtN(busiest[1])+" orders":"", "Avg "+(cur.length/w.days).toFixed(1)+" / day")+
    kpiCard("Draft orders", fmtN(drafts.length), "", "Odoo quotations (draft / sent)")+
    kpiCard("Cancelled", fmtN(cancels.length), "", "Orders placed then voided")+
    `</div>`+
    `<div class='insight-card'><div class='insight-title'>◆ Smart insights</div><ul class='insight-list'>${ins.map(t=>`<li>${t}</li>`).join("")}</ul></div>`+
    sec("Daily orders by shift","Stacked — day vs evening vs off-hours",18)+
    `<div class='card'><div id='shStack'></div></div>
     <div class='grid23' style='margin-top:14px'>
       <div>${sec("Shift split","Share of orders")}<div class='card'><div id='shDonut'></div></div></div>
       <div>${sec("Orders by hour of day","Bar colour marks the shift each hour belongs to")}<div class='card'><div id='shHours'></div></div></div>
     </div>`+
    sec("Order intensity · weekday × hour","Order counts aggregated across the period; brighter = busier",14)+
    `<div class='card'><div id='shHeat'></div></div>`+
    sec("Per-day breakdown","Orders by shift, plus drafts &amp; cancellations",14)+
    `<div class='card' style='padding:12px' id='shTable'></div>`+
    `<div id='shDelivery'></div>`;

  if (cur.length){
    const traces = SHIFT_ORDER_L.map(s=>{
      const y = days.map(dk=>cur.filter(r=>r.dk===dk&&r.shift===s).length);
      if (s===SHIFT_OFF && y.every(v=>!v)) return null;
      return {x:days.map(d=>fmtDayShort(d).slice(0,6)), y, name:s, type:"bar",
        marker:{color:SHIFT_COLORS[s]},
        text:showLbl?y.map(v=>v||""):undefined, textposition:"inside",
        insidetextanchor:"middle", textfont:{size:11,color:"#0A0A0B"}};
    }).filter(Boolean);
    plot("shStack", traces, baseLayout(350,true,{barmode:"stack",
      bargap: w.days<=14?0.32:0.08}));
    const dl=[SHIFT_DAY,SHIFT_EVE], dv=[nDay,nEve],
          dc=[SHIFT_COLORS[SHIFT_DAY],SHIFT_COLORS[SHIFT_EVE]];
    if (nOff){ dl.push(SHIFT_OFF); dv.push(nOff); dc.push(SHIFT_COLORS[SHIFT_OFF]); }
    plot("shDonut", [{labels:dl, values:dv, type:"pie", hole:.64, sort:false,
      marker:{colors:dc, line:{color:PAL.surface,width:2}},
      textinfo:"percent", textfont:{size:12,color:"#0A0A0B"}}],
      baseLayout(300,true,{annotations:[{
        text:`<b style='color:#F4F4F5'>${fmtN(cur.length)}</b><br><span style='font-size:10px;color:#A1A1AA'>orders</span>`,
        x:.5,y:.5,showarrow:false,font:{size:20}}]}));
    const hv = Array.from({length:24},(_,h)=>cur.filter(r=>r.h===h).length);
    plot("shHours", [{x:Array.from({length:24},(_,h)=>String(h).padStart(2,"0")),
      y:hv, type:"bar",
      marker:{color:Array.from({length:24},(_,h)=>SHIFT_COLORS[shiftOf(h)])}}],
      baseLayout(300,false));
    const dows=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
    const z = dows.map((_,d)=>Array.from({length:24},(_,h)=>cur.filter(r=>r.dow===d&&r.h===h).length));
    const tz = z.map(row=>row.map(v=>v?String(v):""));
    plot("shHeat",[{z, x:Array.from({length:24},(_,h)=>String(h).padStart(2,"0")),
      y:dows, type:"heatmap",
      colorscale:[[0,"#0A0A0B"],[0.45,"#3a2f5e"],[1,"#A78BFA"]],
      text:tz, texttemplate:"%{text}", textfont:{size:9,color:"#E4E4E7"},
      showscale:false, xgap:1, ygap:2}], baseLayout(300,false));
  }
  const MAXROWS=45;
  const shown = days.length>MAXROWS ? days.slice(-MAXROWS) : days;
  let tot={d:0,e:0,o:0,t:0,dr:0,cn:0}, body="";
  shown.forEach(dk=>{
    const dd = cur.filter(r=>r.dk===dk);
    const a=sc(dd,SHIFT_DAY), b=sc(dd,SHIFT_EVE), c=sc(dd,SHIFT_OFF);
    const dr = drafts.filter(r=>r.dk===dk).length, cn = cancels.filter(r=>r.dk===dk).length;
    tot.d+=a;tot.e+=b;tot.o+=c;tot.t+=a+b+c;tot.dr+=dr;tot.cn+=cn;
    body+=`<tr><td>${fmtDayShort(dk)}</td><td>${a}</td><td>${b}</td><td>${c}</td><td><b>${a+b+c}</b></td><td>${dr}</td><td>${cn}</td></tr>`;
  });
  body+=`<tr class='tot'><td>Total</td><td>${tot.d}</td><td>${tot.e}</td><td>${tot.o}</td><td>${tot.t}</td><td>${tot.dr}</td><td>${tot.cn}</td></tr>`;
  document.getElementById("shTable").innerHTML =
    (days.length>MAXROWS?`<div class='note'>Showing the most recent ${MAXROWS} of ${days.length} days</div>`:"")+
    `<table class='tbl shift-table'><thead><tr><th>Date</th><th>Day 10–17</th><th>Evening 17–01</th>
     <th>Off 01–10</th><th>Total orders</th><th>Draft</th><th>Cancelled</th></tr></thead><tbody>${body}</tbody></table>`;
  renderDelivery(document.getElementById("shDelivery"), w, days, showLbl);
};

function fmtH(h){
  if (h===null||h===undefined||isNaN(h)) return "—";
  if (h < 1) return Math.round(h*60)+" min";
  if (h < 48) return h.toFixed(1)+" h";
  return (h/24).toFixed(1)+" d";
}
function renderDelivery(el, w, days, showLbl){
  const dd = DLV.filter(r=>state.channels.has(r.ch)&&inWin(r,w.cs,w.ce));
  const done = dd.filter(r=>r.st===0), pend = dd.filter(r=>r.st===1), canc = dd.filter(r=>r.st===2);
  const lead = done.map(r=>r.lead).filter(x=>x!==null);
  const med = median(lead), p90 = quantile(lead,0.9);
  const w2 = lead.length?lead.filter(x=>x<=2).length/lead.length*100:0;
  const w24 = lead.length?lead.filter(x=>x<=24).length/lead.length*100:0;
  const carAgg = groupSum(dd, r=>r.car, ()=>1);
  const topCar = sortEntries(carAgg)[0];
  const SH_SHORT = {[SHIFT_DAY]:"day",[SHIFT_EVE]:"evening",[SHIFT_OFF]:"off-hours"};

  const ins=[];
  if (lead.length){
    ins.push(`Typical delivery completes in <b>${fmtH(med)}</b> (median); 90% land within <b>${fmtH(p90)}</b>.`);
    ins.push(`<b>${w2.toFixed(0)}%</b> of deliveries finish within 2 hours and <b>${w24.toFixed(0)}%</b> within a day.`);
    const shMed = {};
    SHIFT_ORDER_L.forEach(s=>{ const v=done.filter(r=>r.shift===s).map(r=>r.lead).filter(x=>x!==null);
      if (v.length) shMed[s]=median(v); });
    const ks = Object.keys(shMed);
    if (ks.length>=2){
      const fast = ks.reduce((a,b)=>shMed[a]<=shMed[b]?a:b);
      const slow = ks.reduce((a,b)=>shMed[a]>=shMed[b]?a:b);
      ins.push(`Orders placed in the <b>${SH_SHORT[fast]}</b> shift are delivered fastest (median ${fmtH(shMed[fast])}), slowest from the <b>${SH_SHORT[slow]}</b> shift (${fmtH(shMed[slow])}).`);
    }
    const slow = lead.filter(x=>x>48);
    if (slow.length) ins.push(`<b>${slow.length}</b> deliveries took over 2 days (slowest ${fmtH(Math.max(...lead))}) — these drag the average to ${fmtH(mean(lead))}; worth investigating.`);
  }
  if (pend.length) ins.push(`<b>${pend.length}</b> deliveries are currently in transit / awaiting dispatch.`);
  if (canc.length) ins.push(`<b>${canc.length}</b> delivery orders were cancelled this period.`);
  if (!ins.length) ins.push("No completed deliveries with usable timing in this period.");

  el.innerHTML =
    sec("Delivery performance","Real delivery orders (excludes in-store pickups) linked to sales placed in this period · lead time = order placed → delivery completed",24)+
    `<div class='kpi-grid' style='margin-top:6px'>`+
    kpiCard("Deliveries · period", fmtN(dd.length), "", fmtN(done.length)+" completed")+
    kpiCard("Typical lead time", fmtH(med), "median order → delivered", "p90: "+fmtH(p90))+
    kpiCard("Within 2 hours", w2.toFixed(0)+"%", "of completed deliveries", "Within 24h: "+w24.toFixed(0)+"%")+
    kpiCard("In transit", fmtN(pend.length), "assigned / awaiting", "not yet delivered")+
    kpiCard("Top carrier", topCar?esc(topCar[0]):"—", topCar?(topCar[1]/dd.length*100).toFixed(0)+"% of deliveries":"", "")+
    kpiCard("Cancelled", fmtN(canc.length), "", "delivery orders voided")+
    `</div>`+
    `<div class='insight-card'><div class='insight-title'>◆ Delivery insights</div><ul class='insight-list'>${ins.map(t=>`<li>${t}</li>`).join("")}</ul></div>`+
    `<div class='grid2' style='margin-top:14px'>
       <div>${sec("Delivery-time distribution","Completed deliveries by lead-time bucket")}<div class='card'><div id='dlvBuckets'></div></div></div>
       <div>${sec("By carrier","Share of delivery orders")}<div class='card'><div id='dlvCar'></div></div></div>
     </div>
     <div class='grid2' style='margin-top:14px'>
       <div>${sec("Median delivery time by order shift","Does the evening rush slow fulfilment?")}<div class='card'><div id='dlvShift'></div></div></div>
       <div>${sec("Deliveries completed · daily","Across the period")}<div class='card'><div id='dlvDaily'></div></div></div>
     </div>
     <div id='fleetTool'></div>`;

  if (lead.length){
    const bn=["<1h","1–2h","2–6h","6–24h","1–2d",">2d"], bc=[0,0,0,0,0,0];
    lead.forEach(h=>{ bc[h<1?0:h<2?1:h<6?2:h<24?3:h<48?4:5]++; });
    plot("dlvBuckets", [{x:bn, y:bc, type:"bar", marker:{color:PAL.neon},
      text:bc.map(v=>v||""), textposition:"outside",
      textfont:{color:PAL.dim,size:10}, cliponaxis:false}], baseLayout(300,false));
  }
  const ce = sortEntries(carAgg);
  if (ce.length) plot("dlvCar", [{labels:ce.map(x=>x[0]), values:ce.map(x=>x[1]),
    type:"pie", hole:.62, marker:{line:{color:PAL.surface,width:2}},
    textinfo:"percent"}], baseLayout(300,true,{annotations:[{
      text:`<b style='color:#F4F4F5'>${fmtN(dd.length)}</b><br><span style='font-size:10px;color:#A1A1AA'>deliveries</span>`,
      x:.5,y:.5,showarrow:false,font:{size:18}}]}));
  const keep = SHIFT_ORDER_L.map(s=>{
    const v=done.filter(r=>r.shift===s).map(r=>r.lead).filter(x=>x!==null);
    return v.length?[s,median(v)]:null; }).filter(Boolean);
  if (keep.length) plot("dlvShift", [{x:keep.map(x=>x[0].split(" ·")[0]),
    y:keep.map(x=>+x[1].toFixed(2)), type:"bar",
    marker:{color:keep.map(x=>SHIFT_COLORS[x[0]])},
    text:keep.map(x=>fmtH(x[1])), textposition:"outside",
    textfont:{color:PAL.dim,size:10}, cliponaxis:false}], baseLayout(300,false));
  if (done.length){
    const dc = days.map(dk=>done.filter(r=>r.doneDk===dk).length);
    plot("dlvDaily", [{x:days.map(d=>fmtDayShort(d).slice(0,6)), y:dc, type:"bar",
      marker:{color:PAL.sky}, text:showLbl?dc.map(v=>v||""):undefined,
      textposition:"outside", textfont:{color:PAL.dim,size:10}, cliponaxis:false}],
      baseLayout(300,false));
  }
  renderFleet(document.getElementById("fleetTool"), done);
}
function renderFleet(el, done){
  el.innerHTML =
    sec("Fleet capacity · do you need another delivery car?","Set the three inputs to match your operation — the verdict recalculates live",20)+
    `<div class='fleet-inputs'>
      <div><label>Delivery cars available now</label><input type='number' id='fCars' min='1' max='50' value='5'></div>
      <div><label>Round-trip minutes per delivery</label><input type='number' id='fRT' min='10' max='240' step='5' value='20'></div>
      <div><label>Orders carried per trip</label><input type='number' id='fBatch' min='1' max='10' value='1'></div>
    </div>
    <div class='kpi-grid' id='fKpis'></div>
    <div id='fVerdict'></div>`+
    sec("Hourly delivery demand vs fleet capacity","Avg deliveries completed per hour on an active day; bars above the line exceed current capacity",14)+
    `<div class='card'><div id='fChart'></div></div>`;
  const recalc = ()=>{
    const cars = +document.getElementById("fCars").value||5;
    const rt = +document.getElementById("fRT").value||20;
    const batch = +document.getElementById("fBatch").value||1;
    const dd2 = done.filter(r=>r.doneDk && r.doneH!==null);
    const byDay = {};
    dd2.forEach(r=>{ (byDay[r.doneDk]=byDay[r.doneDk]||{})[r.doneH]=(byDay[r.doneDk][r.doneH]||0)+1; });
    const peaks = Object.values(byDay).map(h=>Math.max(...Object.values(h)));
    const activeDays = peaks.length;
    const typical = activeDays?mean(peaks):0;
    const p90 = activeDays?Math.round(quantile(peaks,0.9)):0;
    const extreme = activeDays?Math.max(...peaks):0;
    const per = 60/rt*batch, fleet = cars*per;
    const reqT = per?Math.ceil(typical/per):0, reqW = per?Math.ceil(p90/per):0;
    const util = fleet?typical/fleet*100:0;
    const addP = Math.max(0, reqT-cars), addS = Math.max(0, reqW-cars);
    let head, big, txt, color;
    if (!addP && !addS){ head="No increase needed"; big="0"; color=PAL.good;
      txt=`Your <b>${cars}</b> cars cover both the typical evening peak (~${typical.toFixed(0)}/hr) and the busiest hours seen (${p90}/hr). Peak utilisation is ${util.toFixed(0)}%. Keep the fleet as-is.`; }
    else if (!addP){ head="No permanent increase — keep cars on-call for spikes"; big=`+${addS} on-call`; color=PAL.amber;
      txt=`Your <b>${cars}</b> cars cover the typical evening peak (~${typical.toFixed(0)}/hr) at ${util.toFixed(0)}% utilisation, so no permanent car is required. The very busiest hours (${p90}/hr) would need up to <b>${reqW}</b> cars — keep <b>${addS}</b> on-call / part-time for those spikes rather than buying permanently.`; }
    else { head=`Increase your fleet by ${addP} car(s)`; big=`+${addP}`; color=PAL.bad;
      txt=`Your <b>${cars}</b> cars are below the typical evening peak of ~${typical.toFixed(0)}/hr, which needs <b>${reqT}</b> cars. <b>Add ${addP}</b> permanently (${cars} → ${reqT}) to keep up on a normal night; the very busiest hours (${p90}/hr) would need up to ${reqW}, so consider ${Math.max(0,addS-addP)} more on-call on top.`; }
    document.getElementById("fKpis").innerHTML =
      kpiCard("Cars now", cars, "current fleet", "Fleet capacity "+fleet.toFixed(1)+"/hr")+
      kpiCard("Typical peak demand", typical.toFixed(0)+"/hr", "avg of each day's busiest hour", `Busy night (p90): ${p90}/hr · max ${extreme}/hr`)+
      kpiCard("Recommended fleet", reqT, "to cover the typical peak", "Busy nights need "+reqW)+
      kpiCard("Cars to ADD", addP, "permanent, vs what you have", "Peak utilisation: "+util.toFixed(0)+"%")+
      kpiCard("On-call for spikes", addS, "extra cars for worst hours", "part-time / surge")+
      kpiCard("Capacity per car", per.toFixed(1)+"/hr", `at ${rt} min · ${batch}/trip`, "");
    document.getElementById("fVerdict").innerHTML =
      `<div class='verdict' style='border-color:${color}55'>
        <div class='big' style='color:${color}'>${big}<small>cars</small></div>
        <div><div class='vt' style='color:${color}'>◆ Recommendation — ${head}</div>
        <div class='vb'>${txt}</div></div></div>`;
    const prof = Array.from({length:24},(_,h)=>{
      let s=0; Object.values(byDay).forEach(day=>{ s+=day[h]||0; });
      return activeDays?s/activeDays:0; });
    plot("fChart", [{x:Array.from({length:24},(_,h)=>String(h).padStart(2,"0")),
      y:prof.map(v=>+v.toFixed(2)), type:"bar",
      marker:{color:prof.map(v=>v>fleet?PAL.bad:PAL.neon)}}],
      baseLayout(320,false,{shapes:[{type:"line",x0:-0.5,x1:23.5,y0:fleet,y1:fleet,
        line:{color:PAL.violet,width:2,dash:"dash"}}],
        annotations:[{x:0,y:fleet,xanchor:"left",yanchor:"bottom",showarrow:false,
          text:`capacity ${fleet.toFixed(1)}/hr`,font:{color:PAL.violet,size:11}}]}));
  };
  ["fCars","fRT","fBatch"].forEach(id=>document.getElementById(id).oninput=recalc);
  recalc();
}

/* ================= TAB: Products / SKUs ================= */
window.renderSku = function(el, w, ctx){
  const {cur} = ctx;
  el.innerHTML = sec("Products &amp; SKUs", esc(w.label)+" · what's actually selling, from real Odoo order lines (sale.order.line + pos.order.line)");
  if (!cur.length){ el.innerHTML += "<div class='note'>No data in selected window.</div>"; return; }
  const ls = linesFor(cur);
  if (!ls.length){ el.innerHTML += "<div class='note'>No product line data for the active channel + period selection.</div>"; return; }
  const P = LINES.products;
  const agg = {};
  ls.forEach(l=>{ const a=agg[l.p]=agg[l.p]||{units:0,rev:0,mg:0,lines:0};
    a.units+=l.q; a.rev+=l.r; a.mg+=l.g; a.lines++; });
  const arr = Object.entries(agg).map(([pi,a])=>({p:P[+pi], pi:+pi, ...a,
    gm:a.rev?a.mg/a.rev*100:0})).sort((a,b)=>b.rev-a.rev);
  const uniqueSkus = arr.length;
  const totalUnits = arr.reduce((a,x)=>a+x.units,0);
  const totalRev = arr.reduce((a,x)=>a+x.rev,0);
  const totalMg = arr.reduce((a,x)=>a+x.mg,0);
  const avgGm = totalRev?totalMg/totalRev*100:0;
  const top = arr[0];
  const shortTop = top.p.n.length>40 ? top.p.n.slice(0,38)+"…" : top.p.n;

  el.innerHTML +=
    `<div class='kpi-grid'>`+
    kpiCard("Unique SKUs sold", fmtN(uniqueSkus), `<span style='color:#71717A'>across ${fmtN(ls.length)} order lines</span>`, "")+
    kpiCard("Total units", fmtN(totalUnits), "<span style='color:#71717A'>summed across all SKUs</span>", "")+
    kpiCard("Lines revenue", fmtM(totalRev,true), `<span style='color:#71717A'>at ${avgGm.toFixed(1)}% gross margin</span>`, "Profit: "+fmtM(totalMg,true))+
    kpiCard("Best-selling SKU", `<span style='color:#19E3B6;font-size:18px'>${ltr(shortTop)}</span>`,
      `<b>${fmtM(top.rev,true)}</b> <span style='color:#71717A'>· ${(totalRev?top.rev/totalRev*100:0).toFixed(1)}% of revenue</span>`, "")+
    `</div>`+
    `<div class='grid32' style='margin-top:14px'>
      <div>${sec("Top 15 SKUs by revenue","")}<div class='card'><div id='skTop15'></div></div></div>
      <div>${sec("Revenue concentration","Top X SKUs as % of revenue")}<div class='card'><div id='skConc'></div></div></div>
    </div>`+
    sec("Revenue vs margin","Top-right = high volume + high margin (stars). Bottom-right = high volume but thin margin (re-pricing candidates).",14)+
    `<div class='card'><div id='skScatter'></div></div>`+
    sec("All products — detailed", fmtN(uniqueSkus)+" SKUs · sortable, exportable",14)+
    `<div class='card' style='padding:12px' id='skTbl'></div>
     <button class='btn' id='skCsv' style='margin-top:10px'>◌ Download SKUs as CSV</button>`+
    sec("Often bought together","SKU pairs that appeared in the same order most often",14)+
    `<div class='card' style='padding:12px' id='skPairs'></div>`;

  const t15 = arr.slice(0,15);
  plot("skTop15", [{y:t15.map(x=>x.p.n.length>52?x.p.n.slice(0,50)+"…":x.p.n).reverse(),
    x:t15.map(x=>Math.round(x.rev)).reverse(), type:"bar", orientation:"h",
    marker:{color:t15.map(x=>x.rev).reverse(), colorscale:[[0,"#0E5A4A"],[1,"#19E3B6"]]},
    text:t15.map(x=>fmtN(x.rev)).reverse(), textposition:"outside",
    textfont:{color:PAL.dim,size:10}, cliponaxis:false}],
    baseLayout(520,false,{margin:{l:250,r:40,t:12,b:34},
      yaxis:{tickfont:{size:10,color:PAL.muted}}}));
  const revs = arr.map(x=>x.rev);
  const bkt = [["Top 5", revs.slice(0,5).reduce((a,b)=>a+b,0)],
    ["Top 6–10", revs.slice(5,10).reduce((a,b)=>a+b,0)],
    ["Top 11–25", revs.slice(10,25).reduce((a,b)=>a+b,0)],
    ["Top 26–50", revs.slice(25,50).reduce((a,b)=>a+b,0)],
    ["Rest", revs.slice(50).reduce((a,b)=>a+b,0)]];
  plot("skConc", [{labels:bkt.map(b=>b[0]), values:bkt.map(b=>Math.round(b[1])),
    type:"pie", hole:.65, texttemplate:"%{value:,.0f}<br>%{percent}",
    marker:{colors:["#19E3B6","#38BDF8","#A78BFA","#F5B544","#52525B"],
            line:{color:PAL.surface,width:3}},
    textfont:{size:11,color:PAL.text}}],
    baseLayout(520,true,{annotations:[{
      text:`<b>${uniqueSkus}</b><br><span style='font-size:10px;color:#A1A1AA'>SKUs</span>`,
      showarrow:false, font:{size:14,color:PAL.text}}]}));
  const sc50 = arr.filter(x=>x.rev>0).slice(0,50);
  const maxU = Math.max(...sc50.map(x=>x.units),1);
  plot("skScatter", [{x:sc50.map(x=>+x.rev.toFixed(0)), y:sc50.map(x=>+x.gm.toFixed(1)),
    mode:"markers", text:sc50.map(x=>x.p.n),
    marker:{size:sc50.map(x=>x.units/maxU*30+6), color:sc50.map(x=>x.gm),
      colorscale:[[0,"#F87171"],[0.5,"#F5B544"],[1,"#19E3B6"]], showscale:true,
      colorbar:{title:"Margin %", thickness:8, tickfont:{color:"#A1A1AA",size:9}},
      line:{width:.5,color:PAL.border}, opacity:.85},
    hovertemplate:"<b>%{text}</b><br>Revenue: %{x:,.0f} "+CURRENCY+"<br>Margin: %{y:.1f}%<extra></extra>"}],
    baseLayout(440,false,{xaxis:{title:{text:`Revenue (${CURRENCY})`,font:{size:11,color:PAL.muted}},
      showgrid:false, tickfont:{size:10.5,color:PAL.muted}},
      yaxis:{title:{text:"Margin %",font:{size:11,color:PAL.muted}},
      gridcolor:"rgba(255,255,255,0.045)", griddash:"dot",
      tickfont:{size:10.5,color:PAL.muted}, zeroline:false}}));
  const mxRev = arr[0].rev, mxU2 = Math.max(...arr.map(x=>x.units),1);
  const mxShare = Math.max(...arr.map(x=>totalRev?x.rev/totalRev*100:0),1);
  document.getElementById("skTbl").innerHTML =
    `<div style='max-height:520px;overflow:auto'><table class='tbl'><thead><tr>
     <th>Product</th><th>Sub-category</th><th>Group</th><th>Units</th><th>Order lines</th>
     <th>Revenue (${CURRENCY})</th><th>Profit (${CURRENCY})</th><th>Margin %</th><th>% of revenue</th>
     </tr></thead><tbody>`+
    arr.map(x=>`<tr><td>${ltr(x.p.n)}</td><td>${esc(x.p.c)}</td><td>${esc(x.p.g)}</td>
      <td>${progCell(x.units,mxU2,fmtN(x.units),PAL.sky)}</td><td>${fmtN(x.lines)}</td>
      <td>${progCell(x.rev,mxRev,fmtN(x.rev))}</td><td>${fmtN(x.mg)}</td>
      <td>${progCell(Math.max(x.gm,0),100,x.gm.toFixed(1)+"%",PAL.amber)}</td>
      <td>${progCell(totalRev?x.rev/totalRev*100:0,mxShare*1.1,(totalRev?x.rev/totalRev*100:0).toFixed(1)+"%",PAL.violet)}</td></tr>`).join("")+
    `</tbody></table></div>`;
  document.getElementById("skCsv").onclick = ()=>dlCSV(
    `fyxx-skus-${w.cs}-to-${w.ce}.csv`,
    ["Product","Sub-category","Group","Units","Order lines",`Revenue (${CURRENCY})`,`Profit (${CURRENCY})`,"Margin %","% of revenue"],
    arr.map(x=>[x.p.n, x.p.c, x.p.g, Math.round(x.units), x.lines,
      x.rev.toFixed(0), x.mg.toFixed(0), x.gm.toFixed(1),
      (totalRev?x.rev/totalRev*100:0).toFixed(1)]));
  // basket analysis
  const byOrder = {};
  ls.forEach(l=>{ (byOrder[l.src+"|"+l.oid]=byOrder[l.src+"|"+l.oid]||new Set()).add(l.pi); });
  const pairs = {};
  Object.values(byOrder).forEach(s=>{
    const prods = [...s].sort((a,b)=>a-b);
    if (prods.length>=2 && prods.length<=12){
      for (let i=0;i<prods.length;i++)
        for (let j=i+1;j<prods.length;j++){
          const k = prods[i]+"_"+prods[j];
          pairs[k]=(pairs[k]||0)+1;
        }
    }
  });
  const topPairs = sortEntries(pairs).slice(0,15);
  document.getElementById("skPairs").innerHTML = topPairs.length ?
    `<table class='tbl'><thead><tr><th>Pair</th><th>Times bought together</th></tr></thead><tbody>`+
    topPairs.map(([k,n])=>{ const [a,b]=k.split("_").map(Number);
      return `<tr><td>${ltr(P[a].n.slice(0,35))} &nbsp;↔&nbsp; ${ltr(P[b].n.slice(0,35))}</td><td>${fmtN(n)}</td></tr>`; }).join("")+
    `</tbody></table>` :
    "<div class='note'>Not enough multi-line orders in this window for basket analysis.</div>";
};

/* ================= TAB: Loss Orders ================= */
window.renderLoss = function(el, w, ctx){
  const {cur} = ctx;
  el.innerHTML = sec("Orders sold at a loss", esc(w.label)+" · every order whose Odoo margin is negative — sorted worst first");
  const losses = cur.filter(r=>r.mg<0).sort((a,b)=>a.mg-b.mg);
  if (!cur.length){ el.innerHTML += "<div class='note'>No data in selected window.</div>"; return; }
  if (!losses.length){
    el.innerHTML += "<div class='brief-card'><p class='brief-callout brief-good'>No loss-making orders in this period for the selected channels. Every order had a positive (or zero) gross margin.</p></div>";
    return;
  }
  const nLoss = losses.length, nTotal = cur.length;
  const totalLoss = losses.reduce((a,r)=>a+r.mg,0);
  const totalLossRev = losses.reduce((a,r)=>a+r.amt,0);
  const worst = losses[0];
  const worstPct = worst.amt?worst.mg/worst.amt*100:0;
  el.innerHTML +=
    `<div class='kpi-grid'>`+
    kpiCard("Loss-making orders", fmtN(nLoss),
      `<span style='color:#F87171;font-weight:600'>${(nLoss/nTotal*100).toFixed(1)}%</span> <span style='color:#71717A'>of ${fmtN(nTotal)} total orders</span>`, "")+
    kpiCard("Total loss", `<span style='color:#F87171'>${fmtM(Math.abs(totalLoss),true)}</span>`,
      `<span style='color:#71717A'>across ${fmtM(totalLossRev,true)} of revenue sold below cost</span>`, "")+
    kpiCard("Worst single order", `<span style='color:#F87171'>${fmtM(Math.abs(worst.mg))}</span>`,
      `<b>${esc(worst.nm)}</b> · ${ltr(worst.cu)}`,
      `<span style='color:#71717A'>${esc(worst.ch)} · ${worstPct.toFixed(1)}% margin</span>`)+
    kpiCard("Average loss per order", `<span style='color:#F87171'>${fmtM(Math.abs(totalLoss/nLoss))}</span>`,
      "<span style='color:#71717A'>per loss-making order</span>", "")+
    `</div>`+
    `<div class='grid32' style='margin-top:14px'>
      <div>${sec("Loss by channel","Total negative margin per channel")}<div class='card'><div id='lsCh'></div></div></div>
      <div>${sec("Loss share","Where the bleed is concentrated")}<div class='card'><div id='lsPie'></div></div></div>
    </div>`+
    sec("Loss trend","Daily total loss · "+esc(w.label),14)+
    `<div class='card'><div id='lsTrend'></div></div>`+
    `<div class='grid2' style='margin-top:14px'>
      <div>${sec("Worst customers","Cumulative loss across orders")}<div class='card' style='padding:12px' id='lsCust'></div></div>
      <div>${sec("Salespeople with most losses","")}<div class='card' style='padding:12px' id='lsSp'></div></div>
    </div>`+
    sec("Every loss-making order — detailed", fmtN(nLoss)+" orders · sorted by largest loss first",14)+
    `<div class='card' style='padding:12px' id='lsTbl'></div>
     <button class='btn' id='lsCsv' style='margin-top:10px'>◌ Download loss orders as CSV</button>`;

  const chLoss = {};
  losses.forEach(r=>{ const a=chLoss[r.ch]=chLoss[r.ch]||{loss:0,n:0}; a.loss+=r.mg; a.n++; });
  const chArr = Object.entries(chLoss).map(([c,a])=>({c, abs:Math.abs(a.loss), n:a.n}))
    .sort((a,b)=>b.abs-a.abs);
  plot("lsCh", [{y:chArr.map(x=>x.c).reverse(), x:chArr.map(x=>Math.round(x.abs)).reverse(),
    type:"bar", orientation:"h",
    marker:{color:chArr.map(x=>x.abs).reverse(), colorscale:[[0,"#7F1D1D"],[1,"#F87171"]]},
    text:chArr.map(x=>`${fmtN(x.abs)}  (${x.n} orders)`).reverse(),
    textposition:"outside", textfont:{color:PAL.dim,size:11}, cliponaxis:false}],
    baseLayout(360,false));
  plot("lsPie", [{labels:chArr.map(x=>x.c), values:chArr.map(x=>Math.round(x.abs)),
    type:"pie", hole:.65, texttemplate:"%{value:,.0f}<br>%{percent}",
    marker:{colors:chArr.map(x=>CHANNEL_COLORS[x.c]||"#52525B"),
            line:{color:PAL.surface,width:3}},
    textfont:{size:11,color:PAL.text}}],
    baseLayout(360,true,{annotations:[{
      text:`<b style='color:#F87171'>${fmtM(Math.abs(totalLoss),true)}</b><br><span style='font-size:10px;color:#A1A1AA'>Total loss</span>`,
      showarrow:false, font:{size:14,color:PAL.text}}]}));
  const dl = groupSum(losses, r=>r.dk, r=>Math.abs(r.mg));
  const dks = Object.keys(dl).sort();
  const showL = dks.length<=45;
  plot("lsTrend", [{x:dks, y:dks.map(k=>Math.round(dl[k])), type:"bar",
    marker:{color:"#F87171"}, text:showL?dks.map(k=>fmtN(dl[k])):undefined,
    textposition:"outside", textfont:{color:"#F87171",size:10}, cliponaxis:false}],
    baseLayout(300,false));
  const mkTbl = (key, label)=>{
    const g = {};
    losses.forEach(r=>{ const a=g[r[key]]=g[r[key]]||{loss:0,rev:0,n:0};
      a.loss+=r.mg; a.rev+=r.amt; a.n++; });
    const arr2 = Object.entries(g).map(([k,a])=>({k, abs:Math.abs(a.loss), rev:a.rev, n:a.n}))
      .sort((a,b)=>b.abs-a.abs).slice(0,15);
    const mx = Math.max(...arr2.map(x=>x.abs),1);
    return `<table class='tbl'><thead><tr><th>${label}</th><th>Loss orders</th>
      <th>Revenue (${CURRENCY})</th><th>Loss (${CURRENCY})</th></tr></thead><tbody>`+
      arr2.map(x=>`<tr><td>${ltr(x.k)}</td><td>${fmtN(x.n)}</td><td>${fmtN(x.rev)}</td>
        <td>${progCell(x.abs,mx,fmtN(x.abs),PAL.bad)}</td></tr>`).join("")+`</tbody></table>`;
  };
  document.getElementById("lsCust").innerHTML = mkTbl("cu","Customer");
  document.getElementById("lsSp").innerHTML = mkTbl("sp","Salesperson");
  const mxL = Math.abs(worst.mg)||1;
  const timeOf = r=>{ const l=local(r.ts);
    return r.dk+" "+String(l.getUTCHours()).padStart(2,"0")+":"+String(l.getUTCMinutes()).padStart(2,"0"); };
  document.getElementById("lsTbl").innerHTML =
    `<div style='max-height:620px;overflow:auto'><table class='tbl'><thead><tr>
     <th>Reference</th><th>Date</th><th>Channel</th><th>Source</th><th>Customer</th><th>Salesperson</th>
     <th>Revenue (${CURRENCY})</th><th>Cost (${CURRENCY})</th><th>Loss (${CURRENCY})</th><th>Margin %</th><th>State</th>
     </tr></thead><tbody>`+
    losses.map(r=>`<tr><td>${esc(r.nm)}</td><td>${timeOf(r)}</td><td>${esc(r.ch)}</td>
      <td>${r.src===0?"Sales Order":"POS Ticket"}</td><td>${ltr(r.cu)}</td><td>${ltr(r.sp)}</td>
      <td>${fmtN(r.amt)}</td><td>${fmtN(r.amt-r.mg)}</td>
      <td>${progCell(Math.abs(r.mg),mxL,fmtN(Math.abs(r.mg)),PAL.bad)}</td>
      <td>${(r.amt?r.mg/r.amt*100:0).toFixed(1)}%</td><td>${esc(r.st)}</td></tr>`).join("")+
    `</tbody></table></div>`;
  document.getElementById("lsCsv").onclick = ()=>dlCSV(
    `fyxx-loss-orders-${w.cs}-to-${w.ce}.csv`,
    ["Reference","Date","Channel","Source","Customer","Salesperson",`Revenue (${CURRENCY})`,`Cost (${CURRENCY})`,`Loss (${CURRENCY})`,"Margin %","State"],
    losses.map(r=>[r.nm, timeOf(r), r.ch, r.src===0?"Sales Order":"POS Ticket",
      r.cu, r.sp, r.amt.toFixed(0), (r.amt-r.mg).toFixed(0),
      Math.abs(r.mg).toFixed(0), (r.amt?r.mg/r.amt*100:0).toFixed(1), r.st]));
};

/* ================= TAB: Alerts ================= */
window.renderAlerts = function(el, w, ctx){
  const {cur} = ctx;
  const df = dfAll();
  const t = todayLocal();
  const alerts = [];
  if (cur.length){
    // 1) day outliers vs 60d baseline
    const cutoff = dkOf(addDays(t,-59));
    const base = df.filter(r=>r.dk>=cutoff);
    if (base.length){
      const db = groupSum(base, r=>r.dk, r=>r.amt);
      const vals = Object.values(db);
      const mB = mean(vals), sB = std(vals);
      const cd = groupSum(cur, r=>r.dk, r=>r.amt);
      Object.entries(cd).forEach(([d,v])=>{
        if (sB>0){
          const z = (v-mB)/sB;
          if (z>=2) alerts.push(["good","▲",`Outlier high day · ${fmtDayShort(d)}`,
            `Revenue of <b>${fmtM(v,true)}</b> is <b>${z.toFixed(1)}σ above</b> the 60-day mean of ${fmtM(mB,true)}.`]);
          else if (z<=-2) alerts.push(["bad","▼",`Outlier low day · ${fmtDayShort(d)}`,
            `Revenue of <b>${fmtM(v,true)}</b> is <b>${Math.abs(z).toFixed(1)}σ below</b> the 60-day mean.`]);
        }
      });
    }
    // 2) concentration
    const custRev = sortEntries(groupSum(cur, r=>r.cu, r=>r.amt));
    const total = custRev.reduce((a,[,v])=>a+v,0);
    if (custRev.length && total>0){
      const topShare = custRev[0][1]/total*100;
      if (topShare>=25) alerts.push(["warn","◆","Customer concentration risk",
        `<b>${ltr(custRev[0][0])}</b> accounts for <b>${topShare.toFixed(1)}%</b> of revenue this period — single-customer dependency.`]);
      const top10 = custRev.slice(0,10).reduce((a,[,v])=>a+v,0)/total*100;
      if (top10>=70 && custRev.length>=10) alerts.push(["warn","◆","Top-10 concentration",
        `Top 10 customers drive <b>${top10.toFixed(1)}%</b> of revenue — diversification opportunity.`]);
    }
    // 3) channel deceleration vs 4-period baseline
    const span = w.days;
    const chCur = groupSum(cur, r=>r.ch, r=>r.amt);
    Object.entries(chCur).forEach(([ch,v])=>{
      const totals=[];
      for (let i=1;i<=4;i++){
        const ps = dkOf(addDays(parseDK(w.cs), -span*i));
        const pe = dkOf(addDays(parseDK(ps), span-1));
        const rows = df.filter(r=>r.ch===ch&&inWin(r,ps,pe));
        if (rows.length) totals.push(rows.reduce((a,r)=>a+r.amt,0));
      }
      const b = totals.length?mean(totals):0;
      if (b>0){
        const drop = (v-b)/b*100;
        if (drop<=-25) alerts.push(["bad","▼",`${esc(ch)} significantly down`,
          `Revenue of <b>${fmtM(v,true)}</b> is <b>${Math.abs(drop).toFixed(1)}% below</b> the 4-period baseline of ${fmtM(b,true)}.`]);
        else if (drop>=30) alerts.push(["good","▲",`${esc(ch)} significantly up`,
          `Revenue of <b>${fmtM(v,true)}</b> is <b>${drop.toFixed(1)}% above</b> the 4-period baseline of ${fmtM(b,true)}.`]);
      }
    });
    // 4) at-risk regulars
    const refStart = dkOf(addDays(t,-90)), refMid = dkOf(addDays(t,-30));
    const priorW = df.filter(r=>r.dk>=refStart&&r.dk<refMid);
    const recentW = df.filter(r=>r.dk>=refMid&&r.dk<=dkOf(t));
    if (priorW.length){
      const po = groupSum(priorW, r=>r.cu, ()=>1);
      const regulars = Object.keys(po).filter(c=>po[c]>=3);
      const recentSet = new Set(recentW.map(r=>r.cu));
      const atRisk = regulars.filter(c=>!recentSet.has(c));
      if (atRisk.length){
        const arRev = sortEntries(groupSum(priorW.filter(r=>atRisk.includes(r.cu)), r=>r.cu, r=>r.amt));
        const names = arRev.slice(0,5).map(([c,v])=>`&nbsp;&nbsp;• ${ltr(c)} — was ${fmtM(v,true)}`).join("<br>");
        alerts.push(["warn","◆",`${atRisk.length} at-risk regulars`,
          `Customers with 3+ orders in the prior 60 days who haven't ordered in the last 30:<br>${names}`]);
      }
    }
    // 5) margin compression vs 4-period baseline
    const curRevA = cur.reduce((a,r)=>a+r.amt,0), curProfA = cur.reduce((a,r)=>a+r.mg,0);
    const curGmA = curRevA?curProfA/curRevA*100:0;
    let bR=0,bP=0;
    for (let i=1;i<=4;i++){
      const ps = dkOf(addDays(parseDK(w.cs), -span*i));
      const pe = dkOf(addDays(parseDK(ps), span-1));
      const rows = sliceWin(df, ps, pe);
      bR += rows.reduce((a,r)=>a+r.amt,0);
      bP += rows.reduce((a,r)=>a+r.mg,0);
    }
    const bGm = bR?bP/bR*100:0;
    if (bGm>0){
      const ppt = curGmA-bGm;
      if (ppt<=-3) alerts.push(["bad","▼","Margin compression",
        `Gross margin of <b>${curGmA.toFixed(1)}%</b> is <b>${Math.abs(ppt).toFixed(1)}ppt below</b> the 4-period baseline of ${bGm.toFixed(1)}%. Profit dollars: ${fmtM(curProfA,true)} on revenue of ${fmtM(curRevA,true)}.`]);
      else if (ppt>=3) alerts.push(["good","▲","Margin expansion",
        `Gross margin of <b>${curGmA.toFixed(1)}%</b> is <b>${ppt.toFixed(1)}ppt above</b> the 4-period baseline of ${bGm.toFixed(1)}%. Period profit: ${fmtM(curProfA,true)}.`]);
    }
    // 6) loss orders
    const losses = cur.filter(r=>r.mg<0);
    if (losses.length){
      const tl = losses.reduce((a,r)=>a+r.mg,0);
      const worst = sortEntries(groupSum(losses, r=>r.cu, r=>r.mg)).reverse().slice(0,5);
      const names = worst.map(([c,v])=>`&nbsp;&nbsp;• ${ltr(c)} — loss of ${fmtM(Math.abs(v),true)}`).join("<br>");
      alerts.push(["bad","✖",`${losses.length} loss-making orders`,
        `Combined negative margin of <b>${fmtM(Math.abs(tl),true)}</b> this period. Worst customers:<br>${names}`]);
    }
    // 7) channel margin anomalies
    const chP2 = {};
    cur.forEach(r=>{ const a=chP2[r.ch]=chP2[r.ch]||{rev:0,prof:0}; a.rev+=r.amt; a.prof+=r.mg; });
    Object.entries(chP2).forEach(([ch,a])=>{
      let br=[], bp=[];
      for (let i=1;i<=4;i++){
        const ps = dkOf(addDays(parseDK(w.cs), -span*i));
        const pe = dkOf(addDays(parseDK(ps), span-1));
        const rows = df.filter(r=>r.ch===ch&&inWin(r,ps,pe));
        if (rows.length){ br.push(rows.reduce((x,r)=>x+r.amt,0)); bp.push(rows.reduce((x,r)=>x+r.mg,0)); }
      }
      const sumBr = br.reduce((x,y)=>x+y,0);
      if (br.length && sumBr>0){
        const bgm = bp.reduce((x,y)=>x+y,0)/sumBr*100;
        const cgm = a.rev?a.prof/a.rev*100:0;
        const diff = cgm-bgm;
        if (diff<=-5) alerts.push(["bad","▼",`${esc(ch)} margin slipping`,
          `Gross margin of <b>${cgm.toFixed(1)}%</b> is <b>${Math.abs(diff).toFixed(1)}ppt below</b> its 4-period baseline of ${bgm.toFixed(1)}%.`]);
        else if (diff>=5) alerts.push(["good","▲",`${esc(ch)} margin improving`,
          `Gross margin of <b>${cgm.toFixed(1)}%</b> is <b>${diff.toFixed(1)}ppt above</b> its 4-period baseline of ${bgm.toFixed(1)}%.`]);
      }
    });
    // 8) high revenue, thin margin customers
    if (curRevA>0){
      const cp = {};
      cur.forEach(r=>{ const a=cp[r.cu]=cp[r.cu]||{rev:0,prof:0}; a.rev+=r.amt; a.prof+=r.mg; });
      const entries = Object.entries(cp);
      if (entries.length>=10){
        const p90 = quantile(entries.map(([,a])=>a.rev),0.9);
        const lowGm = entries.filter(([,a])=>a.rev>=p90 && (a.rev?a.prof/a.rev*100:0)<15)
          .sort((a,b)=>b[1].rev-a[1].rev).slice(0,5);
        if (lowGm.length){
          const rows = lowGm.map(([c,a])=>`&nbsp;&nbsp;• ${ltr(c)} — ${fmtM(a.rev,true)} rev at ${(a.rev?a.prof/a.rev*100:0).toFixed(1)}% margin`).join("<br>");
          alerts.push(["warn","◆","High revenue, thin margin",
            `Top-decile customers whose gross margin is below 15% — candidates for re-pricing or cost review:<br>${rows}`]);
        }
      }
    }
    // 9) best day callout
    const bd = sortEntries(groupSum(cur, r=>r.dk, r=>r.amt));
    if (bd.length>1){
      const avg = bd.reduce((a,[,v])=>a+v,0)/bd.length;
      if (avg && bd[0][1]/avg>=1.5)
        alerts.push(["good","★",`Standout day · ${fmtDayShort(bd[0][0])}`,
          `<b>${fmtM(bd[0][1],true)}</b> — <b>${(bd[0][1]/avg).toFixed(1)}×</b> the period's daily average.`]);
    }
  }
  el.innerHTML = sec("Anomalies & alerts", esc(w.label)+" · auto-detected outliers and risk signals");
  if (!alerts.length){
    el.innerHTML += "<div class='brief-card'><p class='brief-callout brief-good'>No anomalies detected for this period — performance is within normal ranges across customers and channels.</p></div>";
    return;
  }
  const sevOrder = {bad:0, warn:1, good:2};
  alerts.sort((a,b)=>sevOrder[a[0]]-sevOrder[b[0]]);
  const colors = {bad:["#F87171","rgba(248,113,113,0.10)"],
    warn:["#F5B544","rgba(245,181,68,0.10)"], good:["#22C55E","rgba(34,197,94,0.10)"]};
  el.innerHTML += `<div class='alert-grid'>`+alerts.map(([s,ic,ti,body])=>{
    const [c,bg] = colors[s];
    return `<div class='alert-card' style='border-left:3px solid ${c}'>`+
      `<div class='alert-ic' style='color:${c};background:${bg}'>${ic}</div>`+
      `<div class='alert-body'><div class='alert-title'>${ti}</div>`+
      `<div class='alert-tx'>${body}</div></div></div>`;
  }).join("")+"</div>";
};

/* ================= TAB: Trends ================= */
window.renderTrends = function(el, w, ctx){
  const {cur} = ctx;
  const df = dfAll();
  const yrs = yearsWithData(df);
  const t = todayLocal();
  el.innerHTML =
    sec("Monthly revenue · year-over-year","Same calendar month, compared across years")+
    `<div class='card'><div id='trYoY'></div></div>
     <div class='grid2' style='margin-top:14px'>
      <div>${sec("Daily revenue · "+esc(w.label),"Net of VAT")}<div class='card'><div id='trDaily'></div></div></div>
      <div>${sec("Day-of-week × hour heatmap", esc(w.label))}<div class='card'><div id='trHeat'></div></div></div>
     </div>`;
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const traces = yrs.map((y,i)=>{
    const vals = Array(12).fill(0);
    df.filter(r=>r.y===y).forEach(r=>vals[r.m-1]+=r.amt);
    const color = y===t.getUTCFullYear() ? PAL.neon : YEAR_COLORS[i%YEAR_COLORS.length];
    return {x:months, y:vals.map(v=>Math.round(v)), name:String(y),
      mode:"lines+markers+text",
      line:{width:2.4,color,shape:"spline",smoothing:.6}, marker:{size:6,color},
      text:vals.map(v=>v?fmtN(v):""), textposition:"top center",
      textfont:{color,size:10}, cliponaxis:false};
  });
  plot("trYoY", traces, baseLayout(380,true));
  const daily = groupSum(cur, r=>r.dk, r=>r.amt);
  const dks = Object.keys(daily).sort();
  const showL = dks.length<=45;
  plot("trDaily", [{x:dks, y:dks.map(k=>Math.round(daily[k])), type:"bar",
    marker:{color:PAL.neon}, text:showL?dks.map(k=>fmtN(daily[k])):undefined,
    textposition:"outside", textfont:{color:PAL.dim,size:10}, cliponaxis:false}],
    baseLayout(320,false));
  const dows=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
  const z = dows.map((_,d)=>Array.from({length:24},(_,h)=>{
    let s=0; cur.forEach(r=>{ if(r.dow===d&&r.h===h) s+=r.amt; }); return Math.round(s); }));
  const tz = z.map(row=>row.map(v=>v>0?fmtN(v):""));
  plot("trHeat", [{z, x:Array.from({length:24},(_,h)=>String(h).padStart(2,"0")), y:dows,
    type:"heatmap", colorscale:[[0,"#0A0A0B"],[0.4,"#0E5A4A"],[1,"#19E3B6"]],
    text:tz, texttemplate:"%{text}", textfont:{size:9,color:"#0A0A0B"},
    showscale:false}], baseLayout(320,false));
};

/* ================= TAB: Channels ================= */
window.renderChannels2 = function(el, w, ctx){
  const {cur, prv} = ctx;
  const df = dfAll();
  const t = todayLocal();
  el.innerHTML =
    sec("Channel performance · current vs prior","Side-by-side, net of VAT")+
    `<div class='card'><div id='ch2Bars'></div></div>
     <div class='grid2' style='margin-top:14px'>
      <div>${sec("Channel × year","")}<div class='card'><div id='ch2Year'></div></div></div>
      <div>${sec("Channel ranking","")}<div class='card' style='padding:12px' id='ch2Tbl'></div></div>
     </div>`;
  const cRev = groupSum(cur, r=>r.ch, r=>r.amt), pRev = groupSum(prv, r=>r.ch, r=>r.amt);
  const chans = [...new Set([...Object.keys(cRev),...Object.keys(pRev)])]
    .sort((a,b)=>(cRev[b]||0)-(cRev[a]||0));
  plot("ch2Bars", [
    {x:chans, y:chans.map(c=>Math.round(pRev[c]||0)), name:"Prior period", type:"bar",
     marker:{color:PAL.border_lt}, text:chans.map(c=>fmtN(pRev[c]||0)),
     textposition:"outside", textfont:{color:PAL.dim,size:10}, cliponaxis:false},
    {x:chans, y:chans.map(c=>Math.round(cRev[c]||0)), name:"Current", type:"bar",
     marker:{color:PAL.neon}, text:chans.map(c=>fmtN(cRev[c]||0)),
     textposition:"outside", textfont:{color:PAL.neon,size:10}, cliponaxis:false},
  ], baseLayout(380,true,{barmode:"group",bargap:.25,bargroupgap:.08}));
  const yrs = yearsWithData(df);
  const cyAgg = {};
  df.forEach(r=>{ if (yrs.includes(r.y)){
    (cyAgg[r.ch]=cyAgg[r.ch]||{})[r.y]=(cyAgg[r.ch][r.y]||0)+r.amt; } });
  const chSorted = Object.keys(cyAgg).sort((a,b)=>
    (cyAgg[a][yrs[yrs.length-1]]||0)-(cyAgg[b][yrs[yrs.length-1]]||0));
  const traces = yrs.map((y,i)=>{
    const color = y===t.getUTCFullYear() ? PAL.neon : YEAR_COLORS[i%YEAR_COLORS.length];
    return {y:chSorted, x:chSorted.map(c=>Math.round(cyAgg[c][y]||0)), name:String(y),
      type:"bar", orientation:"h", marker:{color},
      text:chSorted.map(c=>fmtN(cyAgg[c][y]||0)), textposition:"outside",
      textfont:{color,size:10}, cliponaxis:false};
  });
  plot("ch2Year", traces, baseLayout(380,true,{barmode:"group"}));
  const rank = chans.map(c=>{
    const cc = cur.filter(r=>r.ch===c);
    return {c, rev:cRev[c]||0, n:cc.length, aov:cc.length?(cRev[c]||0)/cc.length:0};
  }).sort((a,b)=>b.rev-a.rev);
  const mx = Math.max(...rank.map(x=>x.rev),1);
  document.getElementById("ch2Tbl").innerHTML =
    `<table class='tbl'><thead><tr><th>Channel</th><th>Revenue (${CURRENCY})</th>
     <th>Orders</th><th>AOV (${CURRENCY})</th></tr></thead><tbody>`+
    rank.map(x=>`<tr><td><span style='color:${CHANNEL_COLORS[x.c]||PAL.text}'>●</span> ${esc(x.c)}</td>
      <td>${progCell(x.rev,mx,fmtN(x.rev))}</td><td>${fmtN(x.n)}</td><td>${fmtN(x.aov)}</td></tr>`).join("")+
    `</tbody></table>`;
};

/* ================= TAB: Customers ================= */
window.renderCustomers2 = function(el, w, ctx){
  const {cur} = ctx;
  el.innerHTML = `<div class='grid3'>
    <div>${sec("Top 20 customers","")}<div class='card' style='padding:12px' id='cu1'></div></div>
    <div>${sec("Customers by orders","")}<div class='card' style='padding:12px' id='cu2'></div></div>
    <div>${sec("Distribution","")}<div class='card'><div id='cu3'></div></div></div>
  </div>`;
  if (!cur.length){ document.getElementById("cu1").innerHTML="<div class='note'>No data.</div>"; return; }
  const rev = sortEntries(groupSum(cur, r=>r.cu, r=>r.amt));
  const mx1 = rev.length?rev[0][1]:1;
  document.getElementById("cu1").innerHTML =
    `<table class='tbl'><thead><tr><th>Customer</th><th>Revenue (${CURRENCY})</th></tr></thead><tbody>`+
    rev.slice(0,20).map(([c,v])=>`<tr><td>${ltr(c)}</td><td>${progCell(v,mx1,fmtN(v))}</td></tr>`).join("")+
    `</tbody></table>`;
  const byN = {};
  cur.forEach(r=>{ const a=byN[r.cu]=byN[r.cu]||{n:0,rev:0}; a.n++; a.rev+=r.amt; });
  const ordArr = Object.entries(byN).map(([c,a])=>({c,...a})).sort((a,b)=>b.n-a.n).slice(0,20);
  const mxN = Math.max(...ordArr.map(x=>x.n),1), mxR = Math.max(...ordArr.map(x=>x.rev),1);
  document.getElementById("cu2").innerHTML =
    `<table class='tbl'><thead><tr><th>Customer</th><th>Orders</th><th>Revenue (${CURRENCY})</th></tr></thead><tbody>`+
    ordArr.map(x=>`<tr><td>${ltr(x.c)}</td><td>${progCell(x.n,mxN,fmtN(x.n),PAL.sky)}</td>
      <td>${progCell(x.rev,mxR,fmtN(x.rev))}</td></tr>`).join("")+
    `</tbody></table>`;
  const total = rev.reduce((a,[,v])=>a+v,0);
  const top10 = rev.slice(0,10).reduce((a,[,v])=>a+v,0);
  const top50 = rev.slice(0,50).reduce((a,[,v])=>a+v,0);
  plot("cu3", [{labels:["Top 10","Top 11–50","Rest"],
    values:[Math.round(top10),Math.round(top50-top10),Math.round(total-top50)],
    type:"pie", hole:.65, texttemplate:"%{value:,.0f}<br>%{percent}",
    marker:{colors:[PAL.neon,PAL.amber,PAL.border_lt], line:{color:PAL.surface,width:3}},
    textfont:{size:11,color:PAL.text}}],
    baseLayout(360,true,{annotations:[{
      text:`<b>${fmtN(rev.length)}</b><br><span style='font-size:10px;color:#A1A1AA'>Customers</span>`,
      showarrow:false, font:{size:14,color:PAL.text}}]}));
};

/* ================= TAB: Cohorts ================= */
const COHORT_EXCLUDE = new Set(["walk-in","walk in","fyxx operations (b2c)","fyxx operations","—","-",""]);
window.renderCohorts = function(el, w, ctx){
  const df = dfAll().filter(r=>!COHORT_EXCLUDE.has(String(r.cu).trim().toLowerCase()));
  const excludedN = dfAll().length - df.length;
  el.innerHTML = sec("Customer cohorts &amp; retention","Each row is a customer's first-purchase month; columns show the % that came back N months later");
  if (!df.length){ el.innerHTML += "<div class='note'>No real customer data available after excluding walk-ins and internal entries.</div>"; return; }
  const monthNum = mk=>{ const [y,m]=mk.split("-").map(Number); return y*12+m-1; };
  const firstMk = {};
  df.forEach(r=>{ if (!(r.cu in firstMk) || r.mk<firstMk[r.cu]) firstMk[r.cu]=r.mk; });
  // retention matrix
  const cohortSets = {};   // cohort -> offset -> Set(customers)
  df.forEach(r=>{
    const c = firstMk[r.cu];
    const off = monthNum(r.mk)-monthNum(c);
    ((cohortSets[c]=cohortSets[c]||{})[off]=cohortSets[c][off]||new Set()).add(r.cu);
  });
  const cohorts = Object.keys(cohortSets).sort();
  const cohortSize = {};
  cohorts.forEach(c=>cohortSize[c]=(cohortSets[c][0]||new Set()).size);
  const m1s = cohorts.map(c=>cohortSize[c]?((cohortSets[c][1]||new Set()).size/cohortSize[c]*100):null)
    .filter(v=>v!==null);
  const m1Repeat = m1s.length?mean(m1s):0;
  const allRet = [];
  cohorts.forEach(c=>{ Object.entries(cohortSets[c]).forEach(([off,s])=>{
    if (+off>0 && cohortSize[c]) allRet.push(s.size/cohortSize[c]*100); }); });
  const avgRepeat = allRet.length?mean(allRet):0;
  const totalCust = Object.values(cohortSize).reduce((a,b)=>a+b,0);
  const curReal = ctx.cur.filter(r=>!COHORT_EXCLUDE.has(String(r.cu).trim().toLowerCase()));
  let newRev=0, retRev=0;
  curReal.forEach(r=>{ if (r.mk===firstMk[r.cu]) newRev+=r.amt; else retRev+=r.amt; });
  const newPct = (newRev+retRev)?newRev/(newRev+retRev)*100:0;
  el.innerHTML +=
    (excludedN>0?`<div class='note'>Cohort math excludes <b style='color:#A1A1AA'>${fmtN(excludedN)}</b> rows from <i>Walk-in</i> and <i>Fyxx Operations (B2C)</i> (anonymous / internal). Real customers tracked: ${fmtN(Object.keys(firstMk).length)}.</div>`:"")+
    `<div class='kpi-grid'>`+
    kpiCard("Total customers tracked", fmtN(totalCust), `Across ${cohorts.length} acquisition cohorts`, "")+
    kpiCard("Month-1 repeat rate", m1Repeat.toFixed(1)+"%", "Average % of customers who came back the very next month", "")+
    kpiCard("Avg retention (M1+)", avgRepeat.toFixed(1)+"%", "Mean retention across all months after acquisition", "")+
    kpiCard("New vs returning · "+esc(w.label), newPct.toFixed(0)+"% new",
      `<b>${fmtM(newRev,true)}</b> from new · <b>${fmtM(retRev,true)}</b> from returning`, "")+
    `</div>`+
    sec("Retention heatmap","Cell = % of that cohort still active in that month after first purchase",14)+
    `<div class='card'><div id='coHeat'></div></div>`+
    sec("New vs returning revenue · monthly","",14)+
    `<div class='card'><div id='coNvr'></div></div>`+
    sec("Customer revenue distribution","How concentrated is revenue across customers?",14)+
    `<div class='kpi-grid' id='coLtv'></div>
     <div class='card'><div id='coHist'></div></div>`;
  // heatmap: last 12 cohorts, first 12 offsets
  const last12 = cohorts.slice(-12);
  const maxOff = 12;
  const z = last12.map(c=>Array.from({length:maxOff},(_,off)=>
    cohortSize[c]?((cohortSets[c][off]||new Set()).size/cohortSize[c]*100):0));
  if (last12.length && z.some(row=>row.slice(1).some(v=>v>0))){
    const tz = z.map(row=>row.map(v=>v>0?v.toFixed(0)+"%":""));
    plot("coHeat", [{z, x:Array.from({length:maxOff},(_,o)=>"M+"+o), y:last12,
      type:"heatmap", colorscale:[[0,"#0A0A0B"],[0.5,"#0E5A4A"],[1,"#19E3B6"]],
      text:tz, texttemplate:"%{text}", textfont:{size:10,color:"#F4F4F5"},
      showscale:false, zmin:0, zmax:100}],
      baseLayout(420,false,{yaxis:{autorange:"reversed",
        tickfont:{size:10.5,color:PAL.muted}}}));
  } else document.getElementById("coHeat").innerHTML =
    "<div class='note' style='padding:16px'>Not enough multi-month history yet to build cohort retention.</div>";
  // new vs returning monthly (last 18)
  const nvr = {};
  df.forEach(r=>{ const isNew = r.mk===firstMk[r.cu];
    const a=nvr[r.mk]=nvr[r.mk]||{n:0,r:0}; if (isNew) a.n+=r.amt; else a.r+=r.amt; });
  const mks = Object.keys(nvr).sort().slice(-18);
  plot("coNvr", [
    {x:mks, y:mks.map(m=>Math.round(nvr[m].n)), name:"New", type:"bar",
     marker:{color:PAL.neon}, text:mks.map(m=>fmtN(nvr[m].n)),
     textposition:"inside", textfont:{color:"#07221C",size:10}},
    {x:mks, y:mks.map(m=>Math.round(nvr[m].r)), name:"Returning", type:"bar",
     marker:{color:"#52525B"}, text:mks.map(m=>fmtN(nvr[m].r)),
     textposition:"inside", textfont:{color:"#F4F4F5",size:10}},
  ], baseLayout(320,true,{barmode:"stack"}));
  // LTV
  const ltv = Object.values(groupSum(df, r=>r.cu, r=>r.amt)).sort((a,b)=>b-a);
  if (ltv.length){
    document.getElementById("coLtv").innerHTML =
      kpiCard("Median customer LTV", fmtM(median(ltv)), "", "")+
      kpiCard("90th percentile LTV", fmtM(quantile(ltv,0.9)), "Top 10% of customers spend at least this much", "")+
      kpiCard("99th percentile LTV", fmtM(quantile(ltv,0.99)), "Top 1% threshold", "");
    plot("coHist", [{x:ltv, type:"histogram", nbinsx:40,
      marker:{color:PAL.neon}}],
      baseLayout(300,false,{bargap:.05,
        xaxis:{title:{text:`Customer lifetime revenue (${CURRENCY})`,font:{size:11,color:PAL.muted}},
          showgrid:false, tickfont:{size:10.5,color:PAL.muted}},
        yaxis:{title:{text:"Customers",font:{size:11,color:PAL.muted}},
          gridcolor:"rgba(255,255,255,0.045)", griddash:"dot",
          tickfont:{size:10.5,color:PAL.muted}, zeroline:false}}));
  }
};

/* ================= TAB: Compare ================= */
window.renderCompare = function(el, w, ctx){
  const t = todayLocal();
  const aS = dkOf(new Date(Date.UTC(t.getUTCFullYear(), t.getUTCMonth(), 1))), aE = dkOf(t);
  const bE0 = addDays(new Date(Date.UTC(t.getUTCFullYear(), t.getUTCMonth(), 1)),-1);
  const bS = dkOf(new Date(Date.UTC(bE0.getUTCFullYear(), bE0.getUTCMonth(), 1))), bE = dkOf(bE0);
  el.innerHTML =
    sec("Period comparator","Pick any two date ranges and compare them side-by-side")+
    `<div class='grid2'>
      <div><div style='color:#19E3B6;font-size:11px;font-weight:700;letter-spacing:0.18em;margin-bottom:6px'>PERIOD A</div>
        <div class='dates show'><input type='date' id='cmpAf' value='${aS}'> <span style='color:var(--muted)'>→</span> <input type='date' id='cmpAt' value='${aE}'></div></div>
      <div><div style='color:#A78BFA;font-size:11px;font-weight:700;letter-spacing:0.18em;margin-bottom:6px'>PERIOD B</div>
        <div class='dates show'><input type='date' id='cmpBf' value='${bS}'> <span style='color:var(--muted)'>→</span> <input type='date' id='cmpBt' value='${bE}'></div></div>
    </div>
    <div id='cmpOut'></div>`;
  const recalc = ()=>{
    const df = dfAll();
    const a1 = document.getElementById("cmpAf").value, a2 = document.getElementById("cmpAt").value;
    const b1 = document.getElementById("cmpBf").value, b2 = document.getElementById("cmpBt").value;
    const dfA = sliceWin(df, a1, a2), dfB = sliceWin(df, b1, b2);
    const aRev = dfA.reduce((x,r)=>x+r.amt,0), bRev = dfB.reduce((x,r)=>x+r.amt,0);
    const aAov = dfA.length?aRev/dfA.length:0, bAov = dfB.length?bRev/dfB.length:0;
    const aCu = new Set(dfA.map(r=>r.cu)).size, bCu = new Set(dfB.map(r=>r.cu)).size;
    const dblock = (a,b)=>{
      if (!b) return "<span style='color:#71717A'>—</span>";
      const p=(a-b)/b*100;
      return `<span class='${p>=0?"kpi-delta-up":"kpi-delta-dn"}'>${p>=0?"▲":"▼"} ${Math.abs(p).toFixed(1)}%</span>`; };
    const rows = [
      ["Revenue", fmtM(aRev,true), fmtM(bRev,true), dblock(aRev,bRev)],
      ["Orders", fmtN(dfA.length), fmtN(dfB.length), dblock(dfA.length,dfB.length)],
      ["AOV", fmtM(aAov), fmtM(bAov), dblock(aAov,bAov)],
      ["Customers", fmtN(aCu), fmtN(bCu), dblock(aCu,bCu)],
    ];
    let out = `<div style='margin-top:10px;border:1px solid #23232B;border-radius:14px;overflow:hidden'>`+
      `<div class='cmp-head'><div>Metric</div><div style='color:#19E3B6'>A · ${fmtDay(a1)} → ${fmtDay(a2)}</div>`+
      `<div style='color:#A78BFA'>B · ${fmtDay(b1)} → ${fmtDay(b2)}</div><div>A vs B</div></div>`+
      rows.map(([l,av,bv,dv])=>`<div class='cmp-row'><div class='cmp-l'>${l}</div>`+
        `<div class='cmp-v'>${av}</div><div class='cmp-v'>${bv}</div><div style='font-size:14px;font-weight:600'>${dv}</div></div>`).join("")+
      `</div>`+
      sec("Channel breakdown","",18)+`<div class='card'><div id='cmpCh'></div></div>`;
    document.getElementById("cmpOut").innerHTML = out;
    if (dfA.length||dfB.length){
      const chA = groupSum(dfA, r=>r.ch, r=>r.amt), chB = groupSum(dfB, r=>r.ch, r=>r.amt);
      const all = [...new Set([...Object.keys(chA),...Object.keys(chB)])]
        .sort((x,y)=>Math.max(chB[y]||0,chA[y]||0)-Math.max(chB[x]||0,chA[x]||0));
      plot("cmpCh", [
        {x:all, y:all.map(c=>Math.round(chA[c]||0)), name:"A", type:"bar",
         marker:{color:PAL.neon}, text:all.map(c=>fmtN(chA[c]||0)),
         textposition:"outside", textfont:{color:PAL.neon,size:10}, cliponaxis:false},
        {x:all, y:all.map(c=>Math.round(chB[c]||0)), name:"B", type:"bar",
         marker:{color:PAL.violet}, text:all.map(c=>fmtN(chB[c]||0)),
         textposition:"outside", textfont:{color:PAL.violet,size:10}, cliponaxis:false},
      ], baseLayout(380,true,{barmode:"group",bargap:.25,bargroupgap:.08}));
    } else document.getElementById("cmpCh").innerHTML = "<div class='note' style='padding:16px'>No data in either selected range.</div>";
  };
  ["cmpAf","cmpAt","cmpBf","cmpBt"].forEach(id=>document.getElementById(id).onchange=recalc);
  recalc();
};

/* ================= TAB: Live ================= */
window.renderLive = function(el){
  const df = dfAll();
  const tdk = dkOf(todayLocal());
  const today = df.filter(r=>r.dk===tdk).sort((a,b)=>b.ts-a.ts);
  el.innerHTML = sec("Today's live ticker",
    `Data as of last sync · ${esc(D.meta.generated_at)} (Amman) · refreshes every 30 min`);
  if (!today.length){ el.innerHTML += "<div class='note'>No activity yet today (as of the last data sync).</div>"; return; }
  const timeOf = r=>{ const l=local(r.ts);
    return String(l.getUTCHours()).padStart(2,"0")+":"+String(l.getUTCMinutes()).padStart(2,"0")+":"+String(l.getUTCSeconds()).padStart(2,"0"); };
  el.innerHTML += `<div class='card' style='padding:12px'>
    <div style='max-height:560px;overflow:auto'><table class='tbl'><thead><tr>
    <th>Time</th><th>Reference</th><th>Channel</th><th>Source</th><th>Customer</th>
    <th>Salesperson</th><th>Total (${CURRENCY})</th><th>State</th></tr></thead><tbody>`+
    today.slice(0,150).map(r=>`<tr><td>${timeOf(r)}</td><td>${esc(r.nm)}</td>
      <td><span style='color:${CHANNEL_COLORS[r.ch]||PAL.text}'>●</span> ${esc(r.ch)}</td>
      <td>${r.src===0?"Sales Order":"POS Ticket"}</td><td>${ltr(r.cu)}</td>
      <td>${ltr(r.sp)}</td><td>${fmtN(r.amt)}</td><td>${esc(r.st)}</td></tr>`).join("")+
    `</tbody></table></div></div>`;
};
