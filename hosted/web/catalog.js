/* Fyxx Executive Insights — Catalogue tab.
   One card (or row) per stocked product: website photo, stock, DPLC, price,
   unit margin, YTD units + value and cover days, filtered by channel.

   Definitions (shown in the tab's footnote too):
   - Stock      = on hand across all internal locations / companies (Odoo).
   - DPLC       = Odoo product cost.
   - Price      = Odoo sales price incl. 16% VAT (same as myfyxx.com).
   - Margin     = net price (excl. VAT) − DPLC; % of net price. This is
                  Odoo's own "Margin (Fyxx)" definition.
   - YTD        = 1 Jan → today, selected channels, value excl. VAT, before
                  order-level discounts.
   - Cover days = bottles in stock ÷ average monthly sales (YTD, selected
                  channels), expressed in days — Zeid's definition.         */
"use strict";

const CAT_UI = {
  q: "", cat: "All", sort: "value", stock: "all", shown: 48,
  view: (() => { try { return localStorage.getItem("fyxx_cat_view") || "cards"; } catch (e) { return "cards"; } })(),
};
const CAT_GOLD = "#C9A96E";

// attribute-safe escaping (the shared esc() doesn't escape quotes)
function catA(s) { return esc(s).replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }
// a photo that fails to load becomes the product's monogram
window.catImgFail = function (img) {
  const d = document.createElement("div");
  d.className = "cat-mono" + (img.dataset.sm ? " sm" : "");
  d.textContent = img.dataset.m || "·";
  img.replaceWith(d);
};
function catImg(src, w) {
  if (!src) return "";
  return src + (src.includes("?") ? "&" : "?") + "width=" + w;
}
function catMoney(x, dp = 2) {
  if (x == null || !isFinite(x)) return "—";
  return x.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}
function catInt(x) {
  if (x == null || !isFinite(x)) return "—";
  return Math.round(x).toLocaleString("en-US");
}

/* metrics for one item over the selected channel indexes */
function catMetrics(x, J, W) {
  let u = 0, a = 0, m = 0, r = 0;
  for (const j of J) { u += x.u[j]; a += x.a[j]; m += x.m[j]; r += x.r[j]; }
  const net = x.p ? x.p / (1 + (x.v || 0)) : 0;
  // no cost recorded in Odoo (DPLC 0) => margin unknown, not 100%
  const ok = net > 0 && x.d > 0;
  const mj = ok ? net - x.d : null;
  const mp = ok ? (net - x.d) / net * 100 : null;
  // Zeid's definition: cover = bottles in stock ÷ average monthly sales.
  // W = days elapsed YTD, so this is (stock ÷ avg monthly units) in days.
  const rate = u / W;
  const cover = x.q <= 0 ? 0 : (rate > 0 ? x.q / rate : Infinity);
  return { u, a, m, r, net, mj, mp, cover, rgm: a ? m / a * 100 : null };
}
function catCover(x, k) {
  if (x.q <= 0) return { cls: "out", label: "Out of stock", days: "0" };
  if (!isFinite(k.cover)) return { cls: "idle", label: "No recent sales", days: "∞" };
  // classify on the exact value, display rounded
  const c = k.cover, d = catInt(Math.round(c));
  if (c < 15) return { cls: "crit", label: "Critical", days: d };
  if (c < 30) return { cls: "low", label: "Low", days: d };
  if (c <= 120) return { cls: "ok", label: "Healthy", days: d };
  return { cls: "high", label: "Long cover", days: d };
}

/* ---------- professional Excel export (ExcelJS, loaded on first use) ---------- */
function catLoadExcelJS() {
  if (window.ExcelJS) return Promise.resolve(window.ExcelJS);
  return new Promise((res, rej) => {
    const s = document.createElement("script");
    s.src = "https://cdn.jsdelivr.net/npm/exceljs@4.4.0/dist/exceljs.min.js";
    s.onload = () => res(window.ExcelJS);
    s.onerror = () => rej(new Error("Could not load the Excel library"));
    document.head.appendChild(s);
  });
}

async function catExcel(rows, W, chLabel) {
  const ExcelJS = await catLoadExcelJS();
  const C = D.catalog;
  const wb = new ExcelJS.Workbook();
  wb.creator = "Fyxx Executive Insights";
  wb.created = new Date();
  const ws = wb.addWorksheet("Catalogue", {
    views: [{ state: "frozen", ySplit: 4, xSplit: 2, showGridLines: false }],
    pageSetup: { orientation: "landscape", paperSize: 9, fitToPage: true, fitToWidth: 1, fitToHeight: 0 },
  });
  const F = "Calibri", GOLD = "FFC9A96E", INK = "FF16161A", LINE = "FFE3DED3";
  const cols = [
    ["#", 6], ["Product", 50], ["SKU", 23], ["Category", 14], ["Type", 14], ["Supplier", 16],
    ["Stock level", 12], ["DPLC", 11], ["Price incl. VAT", 13], ["Price excl. VAT", 13],
    ["Margin JOD", 13], ["Margin %", 12], ["YTD units", 12], ["YTD value (JOD)", 13],
    ["Cover days", 12], ["Realised GM %", 13], ["Website", 12],
  ];
  ws.columns = cols.map(([, w]) => ({ width: w }));
  const last = String.fromCharCode(64 + cols.length);      // "Q"

  // title block
  ws.mergeCells(`A1:${last}1`);
  ws.getCell("A1").value = "Fyxx — Product Catalogue";
  ws.getCell("A1").font = { name: F, size: 18, bold: true, color: { argb: INK } };
  ws.mergeCells(`A2:${last}2`);
  ws.getCell("A2").value =
    `YTD ${C.ytd_start} → ${dkOf(todayLocal())}  ·  ${chLabel}  ·  stock as of ${C.generated_at.slice(0, 16)}  ·  ${rows.length.toLocaleString("en-US")} products`;
  ws.getCell("A2").font = { name: F, size: 10, italic: true, color: { argb: "FF6B6B73" } };
  ws.getRow(1).height = 28;

  // header
  const hr = ws.getRow(4);
  cols.forEach(([h], i) => {
    const c = hr.getCell(i + 1);
    c.value = h;
    c.font = { name: F, size: 10, bold: true, color: { argb: GOLD } };
    c.fill = { type: "pattern", pattern: "solid", fgColor: { argb: INK } };
    // labels sit top-left of the cell so Excel's filter arrow (bottom-right) never covers them
    c.alignment = { vertical: "top", horizontal: "left", wrapText: true };
    c.border = { bottom: { style: "medium", color: { argb: GOLD } } };
  });
  hr.height = 36;

  const COVER_FILL = { crit: "FFFBD5D5", out: "FFFBD5D5", low: "FFFDEBC8", ok: "FFD7F2DF", high: "FFD6EEFA", idle: "FFEDEDEF" };
  const days = W;
  rows.forEach(({ x, k }, i) => {
    const r = 5 + i;
    const row = ws.getRow(r);
    const cv = catCover(x, k);
    const net = x.p ? x.p / (1 + (x.v || 0)) : null;
    row.values = [
      i + 1, x.n, x.k || "", x.c, x.t || "", x.s || "",
      Math.round(x.q),
      x.d > 0 ? x.d : null,
      x.p || null,
      x.p ? { formula: `I${r}/(1+${x.v || 0})`, result: net } : null,
      (x.p && x.d > 0) ? { formula: `J${r}-H${r}`, result: k.mj } : null,
      (x.p && x.d > 0) ? { formula: `IF(J${r}>0,K${r}/J${r},"")`, result: k.mp / 100 } : null,
      Math.round(k.u),
      Math.round(k.a),
      { formula: `IF(G${r}<=0,0,IF(M${r}>0,G${r}/(M${r}/${days}),"No sales"))`,
        result: x.q <= 0 ? 0 : (isFinite(k.cover) ? k.cover : "No sales") },
      k.rgm == null ? null : k.rgm / 100,
      x.h ? { text: "View ↗", hyperlink: `${C.store}/products/${x.h}` } : "",
    ];
    row.font = { name: F, size: 10, color: { argb: "FF1F1F23" } };
    ["G", "M", "N"].forEach(c => ws.getCell(`${c}${r}`).numFmt = "#,##0");
    ["H", "I", "J", "K"].forEach(c => ws.getCell(`${c}${r}`).numFmt = "#,##0.00");
    ["L", "P"].forEach(c => ws.getCell(`${c}${r}`).numFmt = "0.0%");
    const cd = ws.getCell(`O${r}`);
    cd.numFmt = "#,##0";
    cd.alignment = { horizontal: "center" };
    cd.fill = { type: "pattern", pattern: "solid", fgColor: { argb: COVER_FILL[cv.cls] } };
    ws.getCell(`A${r}`).alignment = { horizontal: "center" };
    ws.getCell(`A${r}`).font = { name: F, size: 9, color: { argb: "FF8A8A93" } };
    if (x.q <= 0) ws.getCell(`G${r}`).font = { name: F, size: 10, color: { argb: "FFC0392B" }, bold: true };
    if (k.mj != null && k.mj < 0) ws.getCell(`K${r}`).font = { name: F, size: 10, color: { argb: "FFC0392B" } };
    if (x.h) ws.getCell(`Q${r}`).font = { name: F, size: 10, color: { argb: "FF0B5CAD" }, underline: true };
    for (let c = 1; c <= cols.length; c++)
      row.getCell(c).border = { bottom: { style: "hair", color: { argb: LINE } } };
  });

  // totals (SUBTOTAL so they follow Excel's filter)
  const t = 5 + rows.length, endR = t - 1;
  const tr = ws.getRow(t);
  tr.getCell(2).value = "Total (visible rows)";
  tr.getCell(7).value = { formula: `SUBTOTAL(109,G5:G${endR})` };
  tr.getCell(13).value = { formula: `SUBTOTAL(109,M5:M${endR})` };
  tr.getCell(14).value = { formula: `SUBTOTAL(109,N5:N${endR})` };
  [7, 13, 14].forEach(c => tr.getCell(c).numFmt = "#,##0");
  for (let c = 1; c <= cols.length; c++) {
    const cell = tr.getCell(c);
    cell.font = { name: F, size: 10, bold: true, color: { argb: INK } };
    cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FFF2EDE3" } };
    cell.border = { top: { style: "medium", color: { argb: GOLD } } };
  }
  ws.autoFilter = { from: "A4", to: `${last}${endR}` };

  // definitions sheet
  const dsh = wb.addWorksheet("Definitions", {
    views: [{ showGridLines: false }],
    pageSetup: { orientation: "landscape", paperSize: 9, fitToPage: true, fitToWidth: 1, fitToHeight: 1 },
  });
  dsh.columns = [{ width: 22 }, { width: 90 }];
  dsh.getCell("A1").value = "How the figures are calculated";
  dsh.getCell("A1").font = { name: F, size: 14, bold: true };
  [
    ["Stock level", "Bottles on hand across all warehouses and companies (Odoo)."],
    ["DPLC", "Product cost as recorded in Odoo."],
    ["Price incl. VAT", "Odoo selling price including 16% VAT (same as myfyxx.com)."],
    ["Price excl. VAT", "Price incl. VAT ÷ 1.16."],
    ["Margin JOD", "Price excl. VAT − DPLC, per unit."],
    ["Margin %", "Margin JOD ÷ Price excl. VAT."],
    ["YTD units / value", `1 January to date in the selected channels (${chLabel}); value in JOD excl. VAT, before order-level discounts.`],
    ["Cover days", `Stock level ÷ average daily sales (YTD units ÷ ${days} days so far this year).`],
    ["Realised GM %", "Actual gross margin on YTD sales after discounts / channel pricing."],
    ["Colours (cover days)", "Red < 15 days or out of stock · Amber < 30 · Green 30–120 · Blue > 120 · Grey no sales."],
  ].forEach(([a, b], i) => {
    const r = dsh.getRow(3 + i);
    r.values = [a, b];
    r.getCell(1).font = { name: F, size: 10, bold: true };
    r.getCell(2).font = { name: F, size: 10 };
    r.getCell(2).alignment = { wrapText: true, vertical: "top" };
  });

  const buf = await wb.xlsx.writeBuffer();
  const blob = new Blob([buf], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `Fyxx-Catalogue-${dkOf(todayLocal())}.xlsx`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

function catRows() {
  const C = D.catalog;
  const J = C.channels.map((c, j) => state.channels.has(c) ? j : -1).filter(j => j >= 0);
  const W = C.days_ytd || 1;   // average daily (= monthly / 30) YTD sales pace
  const q = CAT_UI.q.trim().toLowerCase();
  let rows = C.items.map(x => ({ x, k: catMetrics(x, J, W) }));
  // only products that matter for the selected channels: in stock, or sold YTD there
  rows = rows.filter(({ x, k }) => x.q > 0 || k.u > 0);
  if (CAT_UI.cat !== "All") rows = rows.filter(({ x }) => x.c === CAT_UI.cat);
  if (q) rows = rows.filter(({ x }) =>
    (x.n + " " + x.k + " " + x.s + " " + x.t + " " + x.c).toLowerCase().includes(q));
  if (CAT_UI.stock === "in") rows = rows.filter(({ x }) => x.q > 0);
  if (CAT_UI.stock === "out") rows = rows.filter(({ x }) => x.q <= 0);
  if (CAT_UI.stock === "low") rows = rows.filter(({ x, k }) => x.q > 0 && isFinite(k.cover) && k.cover < 30);
  const S = {
    value: (a, b) => b.k.a - a.k.a,
    units: (a, b) => b.k.u - a.k.u,
    stock: (a, b) => b.x.q - a.x.q,
    coverAsc: (a, b) => (a.k.cover - b.k.cover) || (b.k.a - a.k.a),
    coverDesc: (a, b) => {
      const ca = isFinite(a.k.cover) ? a.k.cover : 1e12, cb = isFinite(b.k.cover) ? b.k.cover : 1e12;
      return cb - ca;
    },
    marginPct: (a, b) => (b.k.mp ?? -1e9) - (a.k.mp ?? -1e9),
    marginJod: (a, b) => (b.k.mj ?? -1e9) - (a.k.mj ?? -1e9),
    price: (a, b) => b.x.p - a.x.p,
    name: (a, b) => a.x.n.localeCompare(b.x.n),
  };
  rows.sort(S[CAT_UI.sort] || S.value);
  return { rows, J, W };
}

function catCard({ x, k }) {
  const cv = catCover(x, k);
  const ini = (x.n || "·").slice(0, 1);
  const photo = x.img
    ? `<img loading="lazy" decoding="async" alt="${catA(x.n)}" src="${catA(catImg(x.img, 480))}"
         srcset="${catA(catImg(x.img, 480))} 1x, ${catA(catImg(x.img, 900))} 2x"
         data-m="${catA(ini)}" onerror="catImgFail(this)">`
    : `<div class="cat-mono">${esc(ini)}</div>`;
  const link = x.h ? `<a class="cat-link" href="${catA(D.catalog.store)}/products/${encodeURIComponent(x.h)}"
      target="_blank" rel="noopener">View on myfyxx.com ↗</a>` : `<span class="cat-link dim">Not on the website</span>`;
  const mpw = k.mp == null ? 0 : Math.max(0, Math.min(100, k.mp));
  return `<article class="cat-card">
    <div class="cat-plinth">
      ${photo}
      <span class="cat-tag">${esc(x.c)}</span>
      <span class="cat-cover ${cv.cls}" title="${catA(cv.label)}">${cv.days === "∞" ? "∞" : cv.days + "d"}</span>
    </div>
    <div class="cat-body">
      <div class="cat-sup">${esc(x.s || x.t || x.c)}</div>
      <div class="cat-name" role="heading" aria-level="3" title="${catA(x.n)}">${ltr(x.n)}</div>
      <div class="cat-sku">${esc(x.k || "—")}${x.t ? " · " + esc(x.t) : ""}</div>
      <div class="cat-grid">
        <div><span>Stock level</span><b class="${x.q <= 0 ? "neg" : ""}">${catInt(x.q)}</b></div>
        <div><span>Cover days</span><b class="cv-${cv.cls}">${cv.days}</b><i>${esc(cv.label)}</i></div>
        <div><span>DPLC</span><b>${x.d > 0 ? catMoney(x.d) : "—"}</b>${x.d > 0 ? "" : "<i>no cost in Odoo</i>"}</div>
        <div><span>Price</span><b class="gold">${x.p ? catMoney(x.p) : "—"}</b><i>${x.p ? "incl. VAT" : "no price in Odoo"}</i>${x.p ? `<i class="cat-net">${catMoney(k.net)} excl. VAT</i>` : ""}</div>
        <div><span>Margin %</span><b>${k.mp == null ? "—" : k.mp.toFixed(1) + "%"}</b>
          <em class="cat-bar"><em style="width:${mpw}%"></em></em></div>
        <div><span>Margin JOD</span><b class="${k.mj != null && k.mj < 0 ? "neg" : ""}">${catMoney(k.mj)}</b><i>per unit</i></div>
        <div><span>YTD units</span><b>${catInt(k.u)}</b></div>
        <div><span>YTD value</span><b>${catInt(k.a)}</b><i>JOD excl. VAT</i></div>
      </div>
      <div class="cat-foot">${link}</div>
    </div>
  </article>`;
}

function catTable(rows) {
  const th = (key, label, align = "right") =>
    `<th data-sort="${key}" style="text-align:${align};cursor:pointer"
       class="${CAT_UI.sort === key ? "on" : ""}">${label}${CAT_UI.sort === key ? " ▾" : ""}</th>`;
  return `<div class="cat-table-wrap"><table class="tbl cat-table"><thead><tr>
      <th></th>${th("name", "Product", "left")}<th style="text-align:left">Category</th>
      ${th("stock", "Stock")}${th("coverAsc", "Cover days")}<th>DPLC</th>${th("price", "Price incl. VAT")}<th>Price excl. VAT</th>
      ${th("marginPct", "Margin %")}${th("marginJod", "Margin JOD")}
      ${th("units", "YTD units")}${th("value", "YTD value")}<th>Realised GM%</th>
    </tr></thead><tbody>` +
    rows.map(({ x, k }) => {
      const cv = catCover(x, k);
      return `<tr>
        <td class="cat-thumb">${x.img ? `<img loading="lazy" alt="" src="${catA(catImg(x.img, 120))}" data-m="${catA((x.n || "·").slice(0, 1))}" data-sm="1" onerror="catImgFail(this)">` : `<div class="cat-mono sm">${esc((x.n || "·").slice(0, 1))}</div>`}</td>
        <td style="text-align:left">${ltr(x.n)}<div class="cat-sku">${esc(x.k || "")}</div></td>
        <td style="text-align:left">${esc(x.c)}${x.t ? `<div class="cat-sku">${esc(x.t)}</div>` : ""}</td>
        <td class="${x.q <= 0 ? "neg" : ""}">${catInt(x.q)}</td>
        <td><span class="cat-cover inline ${cv.cls}">${cv.days === "∞" ? "∞" : cv.days}</span></td>
        <td>${x.d > 0 ? catMoney(x.d) : "<span title='No cost in Odoo' style='color:#71717A'>—</span>"}</td><td class="gold">${x.p ? catMoney(x.p) : "—"}</td><td>${x.p ? catMoney(k.net) : "—"}</td>
        <td>${k.mp == null ? "—" : k.mp.toFixed(1) + "%"}</td>
        <td class="${k.mj != null && k.mj < 0 ? "neg" : ""}">${catMoney(k.mj)}</td>
        <td>${catInt(k.u)}</td><td>${catInt(k.a)}</td>
        <td>${k.rgm == null ? "—" : k.rgm.toFixed(1) + "%"}</td></tr>`;
    }).join("") + `</tbody></table></div>`;
}

window.renderCatalog = function (el) {
  const C = D.catalog;
  if (!C || !C.items) {
    el.innerHTML = sec("Product Catalogue", "") +
      "<div class='note'>The catalogue hasn't been generated yet — it appears after the next data sync.</div>";
    return;
  }
  const { rows, J, W } = catRows();
  const chLabel = J.length === C.channels.length ? "all channels" : J.map(j => C.channels[j]).join(" + ");
  // summary over the filtered set
  let stockU = 0, stockV = 0, ytdU = 0, ytdV = 0, low = 0, out = 0;
  rows.forEach(({ x, k }) => {
    if (x.q > 0) { stockU += x.q; stockV += x.q * x.d; } else out++;
    ytdU += k.u; ytdV += k.a;
    if (x.q > 0 && isFinite(k.cover) && k.cover < 30) low++;
  });
  const cats = {};
  C.items.forEach(x => { cats[x.c] = (cats[x.c] || 0) + 1; });
  const catList = Object.keys(cats).sort((a, b) => cats[b] - cats[a]);
  const opt = (v, l, cur) => `<option value="${catA(v)}" ${v === cur ? "selected" : ""}>${esc(l)}</option>`;

  el.innerHTML =
    `<div class="cat-hero">
       <div>
         <div class="cat-eyebrow">The Fyxx Collection</div>
         <div class="cat-title" role="heading" aria-level="2">Product Catalogue</div>
         <div class="cat-subtitle">YTD ${esc(C.ytd_start.slice(8, 10) + "/" + C.ytd_start.slice(5, 7))} → today ·
           ${esc(chLabel)} · stock as of ${esc(C.generated_at.slice(0, 16))} · photos from myfyxx.com</div>
       </div>
       <div class="cat-stats">
         <div><span>Products</span><b>${catInt(rows.length)}</b></div>
         <div><span>Stock units</span><b>${catInt(stockU)}</b></div>
         <div><span>Stock at DPLC</span><b>${fmtM(stockV, true)}</b></div>
         <div><span>YTD units</span><b>${catInt(ytdU)}</b></div>
         <div><span>YTD value</span><b>${fmtM(ytdV, true)}</b></div>
         <div><span>Low cover &lt; 30d</span><b class="amber">${catInt(low)}</b></div>
       </div>
     </div>
     <div class="cat-toolbar">
       <input id="catQ" class="cat-search" type="search" placeholder="Search product, SKU, supplier…" value="${catA(CAT_UI.q)}">
       <select id="catCat" class="cat-sel">${opt("All", "All categories", CAT_UI.cat)}${catList.map(c => opt(c, `${c} (${cats[c]})`, CAT_UI.cat)).join("")}</select>
       <select id="catSort" class="cat-sel">
         ${opt("value", "Sort: YTD value", CAT_UI.sort)}${opt("units", "Sort: YTD units", CAT_UI.sort)}
         ${opt("stock", "Sort: stock level", CAT_UI.sort)}${opt("coverAsc", "Sort: cover — lowest first", CAT_UI.sort)}
         ${opt("coverDesc", "Sort: cover — highest first", CAT_UI.sort)}${opt("marginPct", "Sort: margin %", CAT_UI.sort)}
         ${opt("marginJod", "Sort: margin JOD", CAT_UI.sort)}${opt("price", "Sort: price", CAT_UI.sort)}
         ${opt("name", "Sort: name A–Z", CAT_UI.sort)}</select>
       <div class="cat-seg" id="catStock">
         ${[["all", "All"], ["in", "In stock"], ["low", "Low cover"], ["out", "Out of stock"]].map(([v, l]) =>
           `<button data-v="${v}" class="${CAT_UI.stock === v ? "on" : ""}">${l}</button>`).join("")}
       </div>
       <div class="cat-seg" id="catView">
         <button data-v="cards" class="${CAT_UI.view === "cards" ? "on" : ""}" title="Cards">▦ Cards</button>
         <button data-v="list" class="${CAT_UI.view === "list" ? "on" : ""}" title="List">☰ List</button>
       </div>
       <button class="btn cat-xl" id="catXlsx">⇩ Excel</button>
       <button class="btn" id="catCsv" title="Plain CSV">CSV</button>
     </div>
     <div id="catBody"></div>
     <div class="note cat-note">Stock = on hand across all warehouses · DPLC = Odoo cost · Price = sales price incl. 16% VAT ·
       Margin = net price excl. VAT − DPLC (per unit) · YTD = 1 Jan → today in the selected channels, excl. VAT ·
       Cover days = bottles in stock ÷ average monthly sales (YTD, selected channels), shown in days.</div>`;

  const body = document.getElementById("catBody");
  const draw = () => {
    if (!rows.length) {
      body.innerHTML = "<div class='note' style='padding:24px;text-align:center'>No products match these filters.</div>";
      return;
    }
    if (CAT_UI.view === "list") {
      body.innerHTML = catTable(rows.slice(0, Math.max(CAT_UI.shown, 300))) +
        (rows.length > Math.max(CAT_UI.shown, 300) ? `<div class="cat-more"><button class="btn" id="catMore">Show more (${catInt(rows.length - Math.max(CAT_UI.shown, 300))} left)</button></div>` : "");
      body.querySelectorAll("th[data-sort]").forEach(h => h.onclick = () => { CAT_UI.sort = h.dataset.sort; window.renderCatalog(el); });
    } else {
      body.innerHTML = `<div class="cat-cards">${rows.slice(0, CAT_UI.shown).map(catCard).join("")}</div>` +
        (rows.length > CAT_UI.shown ? `<div class="cat-more"><button class="btn" id="catMore">Show more (${catInt(rows.length - CAT_UI.shown)} left)</button></div>` : "");
    }
    const more = document.getElementById("catMore");
    if (more) {
      more.onclick = () => { CAT_UI.shown = (CAT_UI.view === "list" ? Math.max(CAT_UI.shown, 300) : CAT_UI.shown) + (CAT_UI.view === "list" ? 300 : 48); draw(); };
      if ("IntersectionObserver" in window) {      // keep loading as the user scrolls
        const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); more.click(); } },
          { rootMargin: "600px" });
        io.observe(more);
      }
    }
  };
  draw();

  const rerender = () => { CAT_UI.shown = 48; window.renderCatalog(el); };
  let t = null;
  const qEl = document.getElementById("catQ");
  qEl.oninput = () => {
    clearTimeout(t);
    t = setTimeout(() => {
      CAT_UI.q = qEl.value;
      const pos = qEl.selectionStart;
      rerender();
      const n = document.getElementById("catQ");
      n.focus(); try { n.setSelectionRange(pos, pos); } catch (e) {}
    }, 220);
  };
  document.getElementById("catCat").onchange = e => { CAT_UI.cat = e.target.value; rerender(); };
  document.getElementById("catSort").onchange = e => { CAT_UI.sort = e.target.value; rerender(); };
  document.querySelectorAll("#catStock button").forEach(b => b.onclick = () => { CAT_UI.stock = b.dataset.v; rerender(); });
  document.querySelectorAll("#catView button").forEach(b => b.onclick = () => {
    CAT_UI.view = b.dataset.v;
    try { localStorage.setItem("fyxx_cat_view", CAT_UI.view); } catch (e) {}
    rerender();
  });
  const xb = document.getElementById("catXlsx");
  xb.onclick = async () => {
    const label = xb.textContent;
    xb.disabled = true; xb.textContent = "Preparing…";
    try { await catExcel(rows, W, chLabel); }
    catch (e) { alert("Excel export failed: " + e.message); console.error(e); }
    finally { xb.disabled = false; xb.textContent = label; }
  };
  document.getElementById("catCsv").onclick = () => dlCSV(
    `fyxx-catalogue-${dkOf(todayLocal())}.csv`,
    ["Product", "SKU", "Category", "Type", "Supplier", "Stock level", "DPLC", "Price (incl. VAT)", "Price (excl. VAT)",
     "Margin %", "Margin JOD (per unit)", "YTD units", "YTD value (JOD excl. VAT)", "Cover days",
     "Realised GM %", "Channels", "Website"],
    rows.map(({ x, k }) => [x.n, x.k, x.c, x.t, x.s, Math.round(x.q), x.d.toFixed(3), x.p.toFixed(2), k.net ? k.net.toFixed(2) : "",
      k.mp == null ? "" : k.mp.toFixed(1), k.mj == null ? "" : k.mj.toFixed(2), Math.round(k.u),
      k.a.toFixed(0), x.q <= 0 ? 0 : (isFinite(k.cover) ? Math.round(k.cover) : "no recent sales"),
      k.rgm == null ? "" : k.rgm.toFixed(1), chLabel,
      x.h ? `${C.store}/products/${x.h}` : ""]));
};
