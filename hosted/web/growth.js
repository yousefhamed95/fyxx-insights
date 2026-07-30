/* Fyxx Executive Insights — Growth Engine tab.
   Three revenue actions built from purchase history:
     1. Due to Buy   — customers whose personal buying rhythm says "now"
     2. Churn Radar  — regulars whose rhythm has broken (leaving right now)
     3. Menu Matrix  — Stars / Plowhorses / Puzzles / Dogs by popularity x margin
   Pure client-side maths over the same data the rest of the dashboard uses. */
"use strict";

const GROWTH_MIN_VISITS = 3;      // need 3 visits => 2 gaps => a rhythm
const DUE_LOW = 0.80;             // 80% of the way to the next expected visit
const DUE_HIGH = 2.00;            // beyond 2x cadence it's churn, not "due"
const CHURN_AT = 2.20;            // 2.2x their normal gap = actively leaving
const CHURN_MAX_DAYS = 400;       // older than this = gone, not "at risk"

/* ---------------- customer rhythm engine ----------------
   The business is treated as ONE pool: a purchase in any channel counts as
   engagement, and each customer has a single buying rhythm across E-com,
   Retail, TGR, B2B and DF. Buying anywhere keeps them "active"; going quiet
   everywhere is what puts them at risk. Channels are still shown so you know
   where they shop and how to reach them.                                   */
function rhythmOf(dayMap, today){
  const days = Object.keys(dayMap).sort();
  if (days.length < GROWTH_MIN_VISITS) return null;
  const gaps = [];
  for (let i = 1; i < days.length; i++){
    const g = Math.round((parseDK(days[i]) - parseDK(days[i-1])) / 86400000);
    if (g > 0) gaps.push(g);
  }
  if (gaps.length < 2) return null;
  const medGap = median(gaps);
  if (!medGap || medGap > 240) return null;
  const m = mean(gaps), sd = std(gaps);
  const reliability = Math.max(0, Math.min(1, 1 - (m ? sd / m : 1)));
  const last = days[days.length - 1];
  const daysSince = Math.round((today - parseDK(last)) / 86400000);
  return {
    visits: days.length, medGap, reliability, last, daysSince,
    avgVisit: mean(days.map(d => dayMap[d])),
    overdue: daysSince / medGap,
  };
}

function buildCadence(){
  const df = dfAll().filter(r => r.cu && r.cu !== "Walk-in" && r.cu !== "—");
  const cut365 = dkOf(addDays(todayLocal(), -365));
  const byCust = {};
  df.forEach(r => {
    const c = byCust[r.cu] || (byCust[r.cu] = {
      all:{}, byCh:{}, rev:{}, total:0, orders:0, last365:0 });
    c.all[r.dk] = (c.all[r.dk] || 0) + r.amt;              // pooled visits
    const m = c.byCh[r.ch] || (c.byCh[r.ch] = {});         // per-channel visits
    m[r.dk] = (m[r.dk] || 0) + r.amt;
    c.rev[r.ch] = (c.rev[r.ch] || 0) + r.amt;
    c.total += r.amt;
    c.orders++;
    if (r.dk >= cut365) c.last365 += r.amt;
  });

  const today = todayLocal();
  const out = [];
  Object.keys(byCust).forEach(name => {
    const c = byCust[name];
    // ONE rhythm per customer, across every channel they buy from.
    const basis = rhythmOf(c.all, today);
    if (!basis) return;
    const ranked = sortEntries(c.rev).map(e => e[0]);   // channels by spend
    const mainCh = ranked[0] || "—";
    const totalRev = Object.values(c.rev).reduce((s,v) => s + v, 0) || 1;
    const share = (c.rev[mainCh] || 0) / totalRev * 100;
    const runRate = basis.medGap ? basis.avgVisit * (365 / basis.medGap) : 0;
    out.push({
      name, visits: basis.visits, orders: c.orders, total: c.total,
      avgVisit: basis.avgVisit, medGap: basis.medGap,
      reliability: basis.reliability, last: basis.last,
      daysSince: basis.daysSince, overdue: basis.overdue,
      perYear: Math.min(c.last365 || 0, runRate) || (c.last365 || 0),
      channel: mainCh, share,
      multi: ranked.length > 1,
      alsoIn: ranked.slice(1),
    });
  });
  return out;
}

function confBar(v){
  const pct = Math.round(Math.max(0, Math.min(1, v)) * 100);
  const col = pct >= 70 ? PAL.neon : pct >= 45 ? PAL.amber : PAL.muted;
  return `<div class='gconf'><div class='gconf-bg'><div class='gconf-fill' `+
    `style="width:${pct}%;background:${col}"></div></div><span>${pct}%</span></div>`;
}
function chDot(ch){
  return `<span style="color:${CHANNEL_COLORS[ch] || PAL.muted}">&#9679;</span>`;
}
/* Where this customer shops — main channel plus anything else they use.
   The rhythm itself is pooled across all channels; this is just context
   for how to reach them and what to offer. */
function chCell(c){
  const main = `${chDot(c.channel)} ${esc(c.channel)}`;
  const pct = `<span style="color:${PAL.muted}"> ${c.share.toFixed(0)}%</span>`;
  const also = c.alsoIn && c.alsoIn.length
    ? `<div class="gmix">+ ${c.alsoIn.slice(0,3).map(esc).join(", ")}</div>` : "";
  return main + pct + also;
}

/* ---------------- menu engineering ---------------- */
function menuMatrix(cur){
  if (!LINES || !cur.length) return null;
  const ls = linesFor(cur);
  if (!ls.length) return null;
  const P = LINES.products;
  const agg = {};
  ls.forEach(l => {
    const a = agg[l.p] || (agg[l.p] = { u:0, r:0, g:0 });
    a.u += l.q; a.r += l.r; a.g += l.g;
  });
  let arr = Object.keys(agg).map(pi => {
    const a = agg[pi], p = P[+pi];
    return { name: p ? p.n : "—", cat: p ? p.c : "—", sup: p ? p.s : "—",
             units: a.u, rev: a.r, mg: a.g,
             cm: a.u ? a.g / a.u : 0,               // margin per unit
             gmPct: a.r ? a.g / a.r * 100 : 0 };
  }).filter(x => x.units > 0 && x.rev > 0);
  if (arr.length < 4) return null;

  // Menu engineering only makes sense on the CORE range. A 1,000-SKU long
  // tail would produce hundreds of meaningless "puzzles", so keep the
  // products that make up 95% of revenue (and at least 2 units sold).
  const allCount = arr.length;
  const byRev = [...arr].sort((a,b) => b.rev - a.rev);
  const revAll = byRev.reduce((s,x) => s + x.rev, 0);
  const core = [];
  let run = 0;
  for (const x of byRev){
    if (run >= revAll * 0.95 && core.length >= 12) break;
    if (x.units < 2) continue;
    core.push(x); run += x.rev;
  }
  const tail = allCount - core.length;
  const tailRev = revAll - run;
  arr = core.length >= 8 ? core : byRev;

  const totalUnits = arr.reduce((s,x) => s + x.units, 0);
  const totalMg = arr.reduce((s,x) => s + x.mg, 0);
  // classic menu-engineering thresholds
  const popCut = (totalUnits / arr.length) * 0.70;   // 70% of average popularity
  const cmCut = totalUnits ? totalMg / totalUnits : 0;  // avg margin per unit

  arr.forEach(x => {
    const pop = x.units >= popCut, prof = x.cm >= cmCut;
    x.q = pop && prof ? "Star" : pop ? "Plowhorse" : prof ? "Puzzle" : "Dog";
  });
  return { arr, popCut, cmCut, totalUnits, totalMg, tail, tailRev, allCount };
}
const QCOL = { Star:"#19E3B6", Plowhorse:"#38BDF8", Puzzle:"#F5B544", Dog:"#F87171" };
const QNOTE = {
  Star:"Popular AND profitable — feature these, never discount",
  Plowhorse:"Popular but thin margin — raise price or cut cost",
  Puzzle:"Profitable but ignored — reposition, get staff pushing them",
  Dog:"Neither popular nor profitable — candidates to cut",
};

/* ---------------- the tab ---------------- */
window.renderGrowth = function(el, w, ctx){
  const cad = buildCadence();
  const due = cad
    .filter(c => c.overdue >= DUE_LOW && c.overdue <= DUE_HIGH && c.reliability >= 0.30)
    .map(c => Object.assign({ score: c.reliability * c.avgVisit }, c))
    .sort((a,b) => b.score - a.score);
  const churn = cad
    .filter(c => c.overdue >= CHURN_AT && c.daysSince <= CHURN_MAX_DAYS
                 && c.reliability >= 0.20)
    .sort((a,b) => b.perYear - a.perYear);
  const mm = menuMatrix(ctx.cur);

  const dueValue = due.reduce((s,c) => s + c.avgVisit, 0);
  const riskValue = churn.reduce((s,c) => s + c.perYear, 0);
  const stars = mm ? mm.arr.filter(x => x.q === "Star").length : 0;
  const dogs = mm ? mm.arr.filter(x => x.q === "Dog") : [];
  const dogCash = dogs.reduce((s,x) => s + x.rev, 0);

  el.innerHTML =
    sec("Growth Engine",
        "Three actions built from real purchase behaviour — who to call, who you're losing, and what to fix on the menu")+
    `<div class='kpi-grid' style='margin-top:6px'>`+
    kpiCard("Ready to buy now", fmtN(due.length),
      "customers at their re-order point",
      "Expected value: <b style='color:#19E3B6'>" + fmtM(dueValue, true) + "</b>")+
    kpiCard("Slipping away", fmtN(churn.length),
      "regulars past 2&times; their normal gap",
      "Last 12m spend at risk: <b style='color:#F87171'>" + fmtM(riskValue, true) + "</b>")+
    kpiCard("Menu stars", fmtN(stars),
      mm ? "of " + fmtN(mm.arr.length) + " core products" : "no product data",
      "popular AND profitable")+
    kpiCard("Dead weight", fmtN(dogs.length),
      "low sales, low margin",
      "only " + fmtM(dogCash, true) + " of revenue")+
    `</div>`+

    // ---- 1. DUE TO BUY ----
    sec("&#9673;&nbsp; Due to Buy &mdash; today's call list",
        "Every repeat customer has one buying rhythm across the <b>whole business</b> &mdash; a purchase in any channel counts. These are at or past their next expected purchase, ranked by how reliable their pattern is &times; what they normally spend.", 22)+
    `<div class='card' style='padding:12px' id='gDue'></div>
     <button class='btn' id='gDueCsv' style='margin-top:10px'>&#9678; Download call list (CSV)</button>`+

    // ---- 2. CHURN ----
    sec("&#9888;&nbsp; Churn Radar &mdash; losing them right now",
        "Regulars who have gone quiet <b>everywhere</b> &mdash; past 2&times; their normal gap across all channels. Ranked by the revenue they generated in the last 12 months.", 22)+
    `<div class='card' style='padding:12px' id='gChurn'></div>
     <button class='btn' id='gChurnCsv' style='margin-top:10px'>&#9678; Download win-back list (CSV)</button>`+

    // ---- 3. MENU ----
    sec("&#9678;&nbsp; Menu Engineering &mdash; " + esc(w.label),
        "Your core range plotted by how often it sells &times; how much margin it earns per unit. Four quadrants, four different actions."+
        (mm && mm.tail > 0
          ? ` <span style="color:#71717A">(core = ${fmtN(mm.arr.length)} products making 95% of revenue; ${fmtN(mm.tail)} long-tail items worth ${fmtM(mm.tailRev, true)} excluded)</span>`
          : ""), 22)+
    `<div class='note'>Tip: select a single channel above (e.g. <b>TGR</b>) for a true
      menu analysis of that outlet — with all channels on, this is your whole product portfolio.</div>
     <div class='card'><div id='gMenu'></div></div>
     <div class='gquads' id='gQuads'></div>
     <div class='card' style='padding:12px;margin-top:14px' id='gMenuTbl'></div>`;

  /* ---- due table ---- */
  const dueRows = due.slice(0, 40);
  document.getElementById("gDue").innerHTML = dueRows.length ?
    `<div style='max-height:520px;overflow:auto'><table class='tbl'><thead><tr>
      <th>#</th><th>Customer</th><th>Contact about</th><th>Buys every</th>
      <th>Last bought</th><th>Overdue</th><th>Confidence</th><th>Typical basket</th>
     </tr></thead><tbody>`+
    dueRows.map((c,i) => {
      const od = Math.round(c.daysSince - c.medGap);
      const odTxt = od > 0 ? `<span style='color:${PAL.amber}'>+${od}d</span>`
                           : `<span style='color:${PAL.muted}'>due now</span>`;
      return `<tr><td>${i+1}</td><td>${ltr(c.name)}</td>
        <td style='text-align:left'>${chCell(c)}</td>
        <td>${Math.round(c.medGap)} days</td>
        <td>${fmtDay(c.last)} <span style='color:${PAL.muted}'>(${c.daysSince}d)</span></td>
        <td>${odTxt}</td><td>${confBar(c.reliability)}</td>
        <td><b>${fmtM(c.avgVisit)}</b></td></tr>`;
    }).join("")+
    `</tbody></table></div>`
    : "<div class='note'>No customers are at their re-order point right now (needs 3+ visits to learn a rhythm).</div>";

  const dueBtn = document.getElementById("gDueCsv");
  if (dueBtn) dueBtn.onclick = () => dlCSV(
    `fyxx-due-to-buy-${dkOf(todayLocal())}.csv`,
    ["Rank","Customer","Buys every (days)","Last purchase","Days since","Days overdue",
     "Confidence %","Typical basket (JOD)","Visits","Lifetime (JOD)",
     "Main channel","Main channel %","Also buys from"],
    due.map((c,i) => [i+1, c.name, Math.round(c.medGap), c.last, c.daysSince,
      Math.round(c.daysSince - c.medGap), Math.round(c.reliability*100),
      c.avgVisit.toFixed(0), c.visits, c.total.toFixed(0),
      c.channel, c.share.toFixed(0), (c.alsoIn || []).join(" / ")]));

  /* ---- churn table ---- */
  const chRows = churn.slice(0, 40);
  document.getElementById("gChurn").innerHTML = chRows.length ?
    `<div style='max-height:520px;overflow:auto'><table class='tbl'><thead><tr>
      <th>#</th><th>Customer</th><th>Shops at</th><th>Was buying every</th>
      <th>Last bought</th><th>Gap now</th><th>Lifetime</th><th>Last 12m at risk</th>
     </tr></thead><tbody>`+
    chRows.map((c,i) => `<tr><td>${i+1}</td><td>${ltr(c.name)}</td>
      <td style='text-align:left'>${chCell(c)}</td>
      <td>${Math.round(c.medGap)} days</td>
      <td>${fmtDay(c.last)} <span style='color:${PAL.muted}'>(${c.daysSince}d)</span></td>
      <td><span style='color:${PAL.bad}'>${c.overdue.toFixed(1)}&times;</span></td>
      <td>${fmtM(c.total, true)}</td>
      <td><b style='color:${PAL.bad}'>${fmtM(c.perYear, true)}</b></td></tr>`).join("")+
    `</tbody></table></div>`
    : "<div class='note'>No regulars are currently past 2&times; their normal gap — retention looks healthy.</div>";

  const chBtn = document.getElementById("gChurnCsv");
  if (chBtn) chBtn.onclick = () => dlCSV(
    `fyxx-win-back-${dkOf(todayLocal())}.csv`,
    ["Rank","Customer","Was buying every (days)","Last purchase","Days since",
     "Overdue multiple","Lifetime (JOD)","Last 12m spend at risk (JOD)","Visits",
     "Main channel","Main channel %","Also buys from"],
    churn.map((c,i) => [i+1, c.name, Math.round(c.medGap), c.last, c.daysSince,
      c.overdue.toFixed(1), c.total.toFixed(0), c.perYear.toFixed(0), c.visits,
      c.channel, c.share.toFixed(0), (c.alsoIn || []).join(" / ")]));

  /* ---- menu matrix ---- */
  if (!mm){
    document.getElementById("gMenu").innerHTML =
      "<div class='note' style='padding:18px'>Not enough product-line data in this period to build the matrix.</div>";
    document.getElementById("gQuads").innerHTML = "";
    document.getElementById("gMenuTbl").innerHTML = "";
    return;
  }
  const top = [...mm.arr].sort((a,b) => b.rev - a.rev).slice(0, 70);
  const traces = ["Star","Plowhorse","Puzzle","Dog"].map(q => {
    const pts = top.filter(x => x.q === q);
    return {
      x: pts.map(x => +x.units.toFixed(1)),
      y: pts.map(x => +x.cm.toFixed(2)),
      text: pts.map(x => x.name),
      customdata: pts.map(x => [Math.round(x.rev), x.gmPct.toFixed(1)]),
      mode: "markers", type: "scatter", name: q,
      marker: { size: pts.map(x => Math.max(7, Math.min(30, Math.sqrt(x.rev) / 2.2))),
                color: QCOL[q], opacity: .82,
                line: { width: .5, color: "#0A0A0B" } },
      hovertemplate: "<b>%{text}</b><br>Units: %{x:,.0f}<br>"+
                     "Margin/unit: %{y:,.2f} "+CURRENCY+"<br>"+
                     "Revenue: %{customdata[0]:,.0f}<br>GM: %{customdata[1]}%<extra></extra>",
    };
  }).filter(t => t.x.length);

  const maxU = Math.max(...top.map(x => x.units), 1);
  const maxCm = Math.max(...top.map(x => x.cm), 1);
  const minCm = Math.min(0, ...top.map(x => x.cm));
  plot("gMenu", traces, baseLayout(470, true, {
    margin: { l: 62, r: 18, t: 14, b: 48 },
    xaxis: { title: { text: "Units sold  →  popularity", font: { size: 11, color: PAL.muted } },
             showgrid: false, tickfont: { size: 10.5, color: PAL.muted } },
    yaxis: { title: { text: "Margin per unit ("+CURRENCY+")", font: { size: 11, color: PAL.muted } },
             gridcolor: "rgba(255,255,255,0.045)", griddash: "dot",
             tickfont: { size: 10.5, color: PAL.muted }, zeroline: false },
    shapes: [
      { type:"line", x0:mm.popCut, x1:mm.popCut, y0:minCm, y1:maxCm*1.05,
        line:{ color:"#3F3F46", width:1.5, dash:"dash" } },
      { type:"line", x0:0, x1:maxU*1.05, y0:mm.cmCut, y1:mm.cmCut,
        line:{ color:"#3F3F46", width:1.5, dash:"dash" } },
    ],
    annotations: [
      { x:maxU*0.97, y:maxCm*1.0, text:"STARS", showarrow:false,
        font:{ color:QCOL.Star, size:11 }, xanchor:"right" },
      { x:maxU*0.97, y:minCm, text:"PLOWHORSES", showarrow:false,
        font:{ color:QCOL.Plowhorse, size:11 }, xanchor:"right", yanchor:"bottom" },
      { x:0, y:maxCm*1.0, text:"PUZZLES", showarrow:false,
        font:{ color:QCOL.Puzzle, size:11 }, xanchor:"left" },
      { x:0, y:minCm, text:"DOGS", showarrow:false,
        font:{ color:QCOL.Dog, size:11 }, xanchor:"left", yanchor:"bottom" },
    ],
  }));

  document.getElementById("gQuads").innerHTML = ["Star","Plowhorse","Puzzle","Dog"]
    .map(q => {
      const items = mm.arr.filter(x => x.q === q).sort((a,b) => b.rev - a.rev);
      const rev = items.reduce((s,x) => s + x.rev, 0);
      const list = items.slice(0, 5)
        .map(x => `<li>${ltr(x.name.length > 34 ? x.name.slice(0,32)+"…" : x.name)}</li>`).join("");
      return `<div class='gquad' style='border-color:${QCOL[q]}55'>
        <div class='gquad-h' style='color:${QCOL[q]}'>${q.toUpperCase()}S
          <span>${items.length} items · ${fmtM(rev, true)}</span></div>
        <div class='gquad-n'>${QNOTE[q]}</div>
        <ul class='gquad-l'>${list || "<li style='color:#71717A'>none</li>"}</ul></div>`;
    }).join("");

  const sorted = [...mm.arr].sort((a,b) => b.rev - a.rev);
  const mxRev = sorted.length ? sorted[0].rev : 1;
  document.getElementById("gMenuTbl").innerHTML =
    `<div style='max-height:460px;overflow:auto'><table class='tbl'><thead><tr>
      <th>Product</th><th>Class</th><th>Category</th><th>Units</th>
      <th>Revenue (${CURRENCY})</th><th>Margin/unit</th><th>GM%</th>
     </tr></thead><tbody>`+
    sorted.map(x => `<tr><td>${ltr(x.name)}</td>
      <td><span style='color:${QCOL[x.q]};font-weight:600'>${x.q}</span></td>
      <td>${esc(x.cat)}</td><td>${fmtN(x.units)}</td>
      <td>${progCell(x.rev, mxRev, fmtN(x.rev))}</td>
      <td>${x.cm.toFixed(2)}</td><td>${x.gmPct.toFixed(1)}%</td></tr>`).join("")+
    `</tbody></table></div>`;
};
