"""Send a simple daily SALES-BY-CHANNEL email.

Business day = 00:00 of the target day through 03:00 the NEXT morning
(27 hours, Asia/Amman), so late-night trade counts toward the day it
belongs to. Sent at 07:00 Amman for the day that just closed.

Read-only against Odoo. Python stdlib only — no third-party packages.

Required env vars (GitHub Secrets):
  ODOO_URL, ODOO_DB, ODOO_LOGIN, ODOO_API_KEY
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD
  EMAIL_FROM, EMAIL_TO
Optional:
  EMAIL_CC, REPLY_TO, TARGET_DATE (YYYY-MM-DD | today | yesterday)
"""
from __future__ import annotations

import os
import smtplib
import sys
import xmlrpc.client
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Amman")
DAY_END_HOUR = 3          # business day runs 00:00 -> 03:00 next morning

# ---- business rules (mirrors the dashboard) ----
POS_CONFIG_CHANNEL_MAP = {3: "TGR", 2: "Retail", 5: "Retail", 6: "Retail",
                          7: "TGR", 8: "TGR"}
EXCLUDED_POS_CONFIG_IDS = [4]
_EXCLUDED_CUSTOMER_KEYWORDS = ("fyxx operations", "jt international")
CHANNEL_ORDER = ["E-com", "Retail", "TGR", "B2B", "DF"]
CHANNEL_COLORS = {"E-com": "#19E3B6", "Retail": "#38BDF8", "TGR": "#A78BFA",
                  "B2B": "#F5B544", "DF": "#EC4899"}


def env(name, required=True, default=None):
    v = os.environ.get(name, default)
    if required and not v:
        sys.stderr.write(f"FATAL: env var {name} is not set\n")
        sys.exit(2)
    return v


ODOO_URL = env("ODOO_URL")
ODOO_DB = env("ODOO_DB")
ODOO_LOGIN = env("ODOO_LOGIN")
ODOO_API_KEY = env("ODOO_API_KEY")
SMTP_HOST = env("SMTP_HOST", default="smtp.gmail.com")
SMTP_PORT = int(env("SMTP_PORT", default="587"))
SMTP_USER = env("SMTP_USER")
SMTP_PASSWORD = env("SMTP_PASSWORD")
EMAIL_FROM = env("EMAIL_FROM")
EMAIL_TO = env("EMAIL_TO")
EMAIL_CC = env("EMAIL_CC", required=False, default="")
REPLY_TO = env("REPLY_TO", required=False, default="")


def odoo_client():
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL.rstrip('/')}/xmlrpc/2/common",
                                       allow_none=True)
    uid = common.authenticate(ODOO_DB, ODOO_LOGIN, ODOO_API_KEY, {})
    if not uid:
        sys.stderr.write("FATAL: Odoo authentication failed\n")
        sys.exit(2)
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL.rstrip('/')}/xmlrpc/2/object",
                                       allow_none=True)
    return uid, models


def kw(models, uid, model, method, args, opts=None):
    if method not in {"read", "search", "search_read", "search_count"}:
        raise RuntimeError(f"Refused non-read method: {method}")
    return models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, model, method,
                             args, opts or {})


def _is_internal(name):
    low = (name or "").strip().lower()
    return any(k in low for k in _EXCLUDED_CUSTOMER_KEYWORDS)


def _df_override(name):
    low = (name or "").strip().lower()
    if "jordanian duty free" in low or "duty free shops" in low:
        return "DF"
    return None


def resolve_channel_so(sp, co):
    sp = (sp or "").strip().lower()
    co = (co or "").strip().lower()
    if "fyxx operations" in co:
        if "shopify" in sp:
            return "E-com"
        if "tareq" in sp or "yousef" in sp:
            return "B2B"
    return "Retail"


def _is_retail_at_green_room(category_path):
    """Same rule as the dashboard: a product sold at the Dine-In (TGR)
    register is RETAIL if it's a take-home bottle / cigar; it stays TGR if
    it's consumed on-premise (food, cocktails, by-the-glass, dine-in drinks)."""
    if not category_path:
        return False
    p = " " + category_path.lower() + " "
    if "(dine-in)" in p or "(di)" in p:
        return False
    if "btg" in p:
        return False
    if "/ food /" in p or p.rstrip().endswith("/ food"):
        return False
    if "/ drinks /" in p:
        return False
    if "0% beverage" in p:
        return False
    if "/ cocktails" in p:
        return False
    if "/ alcohol" in p or "/ tobacco" in p or "cigar" in p:
        return True
    return False


def _green_room_split(models, uid, tgr_orders):
    """Given {order_id: (net, vat)} for TGR POS orders, return
    (retail_net, retail_vat, retail_orders, tgr_net, tgr_vat, tgr_orders)
    by reading the order lines and classifying each product — exactly as the
    dashboard's _split_green_room_to_retail does."""
    empty = (0.0, 0.0, 0, 0.0, 0.0, 0)
    if not tgr_orders:
        return empty
    ids = list(tgr_orders.keys())
    lines = []
    for i in range(0, len(ids), 2000):
        try:
            lines += kw(models, uid, "pos.order.line", "search_read",
                        [[["order_id", "in", ids[i:i + 2000]]]],
                        {"fields": ["order_id", "product_id", "price_subtotal"],
                         "limit": 500000})
        except Exception:
            pass
    if not lines:
        return empty
    pids = sorted({l["product_id"][0] for l in lines if l.get("product_id")})
    cats = {}
    for i in range(0, len(pids), 500):
        try:
            for r in kw(models, uid, "product.product", "read",
                        [pids[i:i + 500]], {"fields": ["id", "categ_id"]}):
                cats[r["id"]] = (r["categ_id"][1] if r.get("categ_id") else "") or ""
        except Exception:
            pass

    per_order = defaultdict(lambda: {"retail": 0.0, "dine": 0.0})
    for l in lines:
        if not l.get("order_id") or not l.get("product_id"):
            continue
        net = float(l.get("price_subtotal") or 0)
        bucket = ("retail" if _is_retail_at_green_room(cats.get(l["product_id"][0], ""))
                  else "dine")
        per_order[l["order_id"][0]][bucket] += net

    r_net = r_vat = t_net = t_vat = 0.0
    r_n = t_n = 0
    for oid, (onet, ovat) in tgr_orders.items():
        s = per_order.get(oid)
        total = (s["retail"] + s["dine"]) if s else 0.0
        if not s or total <= 0:
            # no usable line data — leave the whole order on TGR
            t_net += onet; t_vat += ovat; t_n += 1
            continue
        if s["retail"] > 0:
            r_net += s["retail"]; r_vat += ovat * (s["retail"] / total); r_n += 1
        if s["dine"] > 0:
            t_net += s["dine"]; t_vat += ovat * (s["dine"] / total); t_n += 1
    return r_net, r_vat, r_n, t_net, t_vat, t_n


def business_window(target_date):
    """00:00 target_date -> 03:00 the next morning (Amman)."""
    start = datetime.combine(target_date, datetime.min.time(), TZ)
    end = start + timedelta(days=1, hours=DAY_END_HOUR)
    return start, end


def sales_for_day(target_date):
    uid, models = odoo_client()
    start_local, end_local = business_window(target_date)
    su = start_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    eu = end_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    sos = kw(models, uid, "sale.order", "search_read",
             [[["date_order", ">=", su], ["date_order", "<=", eu],
               ["state", "in", ["sale", "done"]]]],
             {"fields": ["partner_id", "user_id", "company_id",
                         "amount_untaxed", "amount_tax", "date_order"],
              "limit": 100000})
    poss = kw(models, uid, "pos.order", "search_read",
              [[["date_order", ">=", su], ["date_order", "<=", eu],
                ["state", "in", ["paid", "done", "invoiced"]],
                ["config_id", "not in", EXCLUDED_POS_CONFIG_IDS]]],
              {"fields": ["partner_id", "config_id", "amount_total",
                          "amount_tax", "date_order"], "limit": 100000})

    ch = defaultdict(lambda: {"orders": 0, "net": 0.0, "vat": 0.0})
    late = {"orders": 0, "net": 0.0}

    def add(channel, net, vat, dt_utc):
        a = ch[channel]
        a["orders"] += 1
        a["net"] += net
        a["vat"] += vat
        dtl = datetime.strptime(dt_utc, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc).astimezone(TZ)
        if dtl.date() != target_date:     # the 00:00-03:00 tail
            late["orders"] += 1
            late["net"] += net

    for o in sos:
        cust = o["partner_id"][1] if o.get("partner_id") else ""
        if _is_internal(cust):
            continue
        sp = o["user_id"][1] if o.get("user_id") else ""
        co = o["company_id"][1] if o.get("company_id") else ""
        channel = _df_override(cust) or resolve_channel_so(sp, co)
        add(channel, float(o.get("amount_untaxed") or 0),
            float(o.get("amount_tax") or 0), o["date_order"])

    tgr_orders = {}          # order_id -> (net, vat) for the Green Room split
    for o in poss:
        cust = o["partner_id"][1] if o.get("partner_id") else "Walk-in"
        if _is_internal(cust):
            continue
        cid = o["config_id"][0] if o.get("config_id") else None
        channel = _df_override(cust) or POS_CONFIG_CHANNEL_MAP.get(
            cid, o["config_id"][1] if o.get("config_id") else "POS")
        net = float(o.get("amount_total") or 0) - float(o.get("amount_tax") or 0)
        vat = float(o.get("amount_tax") or 0)
        if channel == "TGR":
            # held back — split into Retail (bottles/cigars) + TGR below
            tgr_orders[o["id"]] = (net, vat)
            dtl = datetime.strptime(o["date_order"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc).astimezone(TZ)
            if dtl.date() != target_date:
                late["orders"] += 1
                late["net"] += net
            continue
        add(channel, net, vat, o["date_order"])

    # Green Room split: take-home bottles/cigars sold at the Dine-In register
    # are reported as Retail, exactly like the dashboard does.
    if tgr_orders:
        r_net, r_vat, r_n, t_net, t_vat, t_n = _green_room_split(
            models, uid, tgr_orders)
        if r_n or r_net:
            ch["Retail"]["orders"] += r_n
            ch["Retail"]["net"] += r_net
            ch["Retail"]["vat"] += r_vat
        if t_n or t_net:
            ch["TGR"]["orders"] += t_n
            ch["TGR"]["net"] += t_net
            ch["TGR"]["vat"] += t_vat

    keys = ([k for k in CHANNEL_ORDER if k in ch]
            + sorted(k for k in ch if k not in CHANNEL_ORDER))
    rows = [(k, ch[k]["orders"], ch[k]["net"], ch[k]["vat"]) for k in keys]
    total_orders = sum(r[1] for r in rows)
    total_net = sum(r[2] for r in rows)
    total_vat = sum(r[3] for r in rows)
    return {
        "date": target_date,
        "start": start_local,
        "end": end_local,
        "rows": rows,
        "total_orders": total_orders,
        "total_net": total_net,
        "total_vat": total_vat,
        "late": late,
    }


def money(n):
    return f"{n:,.0f}"


def build_html(s):
    rows_html = ""
    for name, orders, net, vat in s["rows"]:
        color = CHANNEL_COLORS.get(name, "#A1A1AA")
        share = (net / s["total_net"] * 100) if s["total_net"] else 0
        rows_html += (
            "<tr>"
            f"<td style='padding:10px 14px;color:#F4F4F5;border-bottom:1px solid #1F1F26'>"
            f"<span style='color:{color}'>&#9679;</span>&nbsp;{name}</td>"
            f"<td style='padding:10px 14px;text-align:right;color:#D4D4D8;"
            f"border-bottom:1px solid #1F1F26'>{orders:,}</td>"
            f"<td style='padding:10px 14px;text-align:right;color:#F4F4F5;font-weight:600;"
            f"border-bottom:1px solid #1F1F26'>{money(net)}</td>"
            f"<td style='padding:10px 14px;text-align:right;color:#A1A1AA;"
            f"border-bottom:1px solid #1F1F26'>{share:.0f}%</td>"
            "</tr>"
        )
    if not s["rows"]:
        rows_html = ("<tr><td colspan='4' style='padding:16px;text-align:center;"
                     "color:#71717A'><i>No sales recorded for this day.</i></td></tr>")

    late_note = ""
    if s["late"]["orders"]:
        late_note = (
            f"<div style='margin-top:14px;color:#A1A1AA;font-size:12px'>"
            f"Includes <b style='color:#F4F4F5'>{s['late']['orders']}</b> order(s) "
            f"worth <b style='color:#F4F4F5'>{money(s['late']['net'])} JOD</b> "
            f"placed after midnight (00:00&ndash;03:00).</div>")

    gross = s["total_net"] + s["total_vat"]
    return f"""
<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="background:#0A0A0B;font-family:'Segoe UI',Helvetica,Arial,sans-serif;
             color:#D4D4D8;padding:24px;margin:0">
  <div style="max-width:640px;margin:0 auto;background:#111114;
              border:1px solid #23232B;border-radius:14px;padding:28px 30px">

    <div style="color:#19E3B6;font-size:11px;font-weight:700;letter-spacing:0.18em;
                text-transform:uppercase;margin-bottom:6px">Fyxx Daily Sales</div>
    <h1 style="color:#F4F4F5;font-size:22px;font-weight:700;margin:0 0 4px 0;
               letter-spacing:-0.01em">{s['date'].strftime('%A, %d %b %Y')}</h1>
    <div style="color:#71717A;font-size:12px;margin-bottom:22px">
      Business day &middot; {s['start'].strftime('%d %b %H:%M')} &rarr;
      {s['end'].strftime('%d %b %H:%M')} (incl. after-midnight sales)
    </div>

    <div style="background:#15151A;border:1px solid #23232B;border-radius:10px;
                padding:16px 18px;margin-bottom:20px">
      <div style="color:#71717A;font-size:11px;text-transform:uppercase;
                  letter-spacing:0.12em;margin-bottom:6px">Total sales (excl. VAT)</div>
      <div style="color:#19E3B6;font-size:30px;font-weight:800;
                  font-variant-numeric:tabular-nums">{money(s['total_net'])} JOD</div>
      <div style="color:#A1A1AA;font-size:12px;margin-top:6px">
        {s['total_orders']:,} orders &middot; VAT {money(s['total_vat'])} &middot;
        incl. VAT {money(gross)} JOD</div>
    </div>

    <table style="width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums">
      <thead><tr style="background:#16161B">
        <th style="text-align:left;padding:9px 14px;color:#71717A;font-size:10px;
                   text-transform:uppercase;letter-spacing:0.10em">Channel</th>
        <th style="text-align:right;padding:9px 14px;color:#71717A;font-size:10px;
                   text-transform:uppercase;letter-spacing:0.10em">Orders</th>
        <th style="text-align:right;padding:9px 14px;color:#71717A;font-size:10px;
                   text-transform:uppercase;letter-spacing:0.10em">Net (JOD)</th>
        <th style="text-align:right;padding:9px 14px;color:#71717A;font-size:10px;
                   text-transform:uppercase;letter-spacing:0.10em">Share</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
      <tfoot><tr style="background:rgba(25,227,182,0.05)">
        <td style="padding:11px 14px;color:#F4F4F5;font-weight:700;
                   border-top:1px solid #2A2A33">Total</td>
        <td style="padding:11px 14px;text-align:right;color:#F4F4F5;font-weight:700;
                   border-top:1px solid #2A2A33">{s['total_orders']:,}</td>
        <td style="padding:11px 14px;text-align:right;color:#19E3B6;font-weight:700;
                   border-top:1px solid #2A2A33">{money(s['total_net'])}</td>
        <td style="padding:11px 14px;text-align:right;color:#A1A1AA;
                   border-top:1px solid #2A2A33">100%</td>
      </tr></tfoot>
    </table>
    {late_note}

    <div style="margin-top:24px;padding-top:14px;border-top:1px solid #1F1F26;
                color:#52525B;font-size:11px;text-align:center">
      Generated automatically by the Fyxx Insights pipeline
    </div>
  </div>
</body></html>
"""


def build_plain(s):
    lines = [
        "Fyxx Daily Sales",
        f"{s['date'].strftime('%A, %d %b %Y')}",
        f"Business day: {s['start'].strftime('%d %b %H:%M')} -> "
        f"{s['end'].strftime('%d %b %H:%M')} (includes after-midnight sales)",
        "",
        f"TOTAL: {money(s['total_net'])} JOD net  |  {s['total_orders']:,} orders"
        f"  |  VAT {money(s['total_vat'])}",
        "",
        f"{'Channel':10}{'Orders':>8}{'Net (JOD)':>14}{'Share':>8}",
    ]
    for name, orders, net, vat in s["rows"]:
        share = (net / s["total_net"] * 100) if s["total_net"] else 0
        lines.append(f"{name:10}{orders:>8,}{money(net):>14}{share:>7.0f}%")
    lines.append("")
    if s["late"]["orders"]:
        lines.append(f"Includes {s['late']['orders']} order(s) worth "
                     f"{money(s['late']['net'])} JOD placed 00:00-03:00.")
    lines.append("Generated automatically by the Fyxx Insights pipeline.")
    return "\n".join(lines)


def send_email(s):
    subject = (f"Fyxx Daily Sales — {s['date'].strftime('%d %b %Y')} — "
               f"{money(s['total_net'])} JOD ({s['total_orders']} orders)")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    if EMAIL_CC:
        msg["Cc"] = EMAIL_CC
    if REPLY_TO:
        msg["Reply-To"] = REPLY_TO
    msg.attach(MIMEText(build_plain(s), "plain", "utf-8"))
    msg.attach(MIMEText(build_html(s), "html", "utf-8"))

    to_list = [r.strip() for r in EMAIL_TO.split(",") if r.strip()]
    cc_list = [r.strip() for r in EMAIL_CC.split(",") if r.strip()] if EMAIL_CC else []

    print(f"Connecting to {SMTP_HOST}:{SMTP_PORT} as {SMTP_USER} ...")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.ehlo(); server.starttls(); server.ehlo()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(EMAIL_FROM, to_list + cc_list, msg.as_string())
    print(f"Sent to {EMAIL_TO}" + (f" (cc {EMAIL_CC})" if EMAIL_CC else "") + " OK.")


def _already_sent_today():
    """True if an earlier *scheduled* run of this workflow already succeeded
    in the last 12 hours — so the backup cron fires don't double-send."""
    if os.environ.get("GITHUB_EVENT_NAME") != "schedule":
        return False
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    wf = os.environ.get("WORKFLOW_FILE", "daily-sales-email.yml")
    cur_id = os.environ.get("GITHUB_RUN_ID", "")
    if not (repo and token):
        return False
    import json
    import urllib.request
    url = (f"https://api.github.com/repos/{repo}/actions/workflows/"
           f"{wf}/runs?status=success&per_page=10")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        sys.stderr.write(f"WARN: dedup check failed: {e}\n")
        return False   # fail open — better a duplicate than a miss
    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    for r in data.get("workflow_runs", []):
        if str(r.get("id")) == cur_id or r.get("event") != "schedule":
            continue
        try:
            upd = datetime.strptime(r.get("updated_at", ""),
                                    "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if upd >= cutoff:
            print(f"Dedup: scheduled run {r.get('id')} already sent at "
                  f"{r.get('updated_at')} — skipping.")
            return True
    return False


def _resolve_target_date():
    """Default = the day that just closed. Sent at 07:00, that's yesterday."""
    today = datetime.now(TZ).date()
    raw = (os.environ.get("TARGET_DATE") or "").strip().lower()
    if not raw or raw == "yesterday":
        return today - timedelta(days=1), "yesterday"
    if raw == "today":
        return today, "today"
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date(), f"override={raw}"
    except ValueError:
        sys.stderr.write(f"WARN: bad TARGET_DATE={raw!r}, using yesterday\n")
        return today - timedelta(days=1), "yesterday"


def main():
    if _already_sent_today():
        return
    target, label = _resolve_target_date()
    print(f"Target business day (Asia/Amman): {target}  [{label}]")
    s = sales_for_day(target)
    print(f"Window: {s['start']:%Y-%m-%d %H:%M} -> {s['end']:%Y-%m-%d %H:%M}")
    print(f"Total: {money(s['total_net'])} JOD net across "
          f"{s['total_orders']} orders; late tail "
          f"{s['late']['orders']} orders / {money(s['late']['net'])} JOD")
    for name, orders, net, vat in s["rows"]:
        print(f"   {name:10} {orders:>6} orders  {money(net):>12} JOD")
    send_email(s)


if __name__ == "__main__":
    main()
