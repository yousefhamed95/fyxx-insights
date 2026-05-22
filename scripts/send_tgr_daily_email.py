"""Send a daily TGR customer summary email.

Designed to run unattended via GitHub Actions at the end of each Amman day.
Pulls TGR (POS Dine-In, config_id=3) orders for today (Asia/Amman), groups
them into named vs walk-in customers, builds an HTML email, and sends via
SMTP.

Read-only against Odoo. No third-party packages — Python stdlib only.

Required environment variables (set as GitHub Secrets):
  ODOO_URL, ODOO_DB, ODOO_LOGIN, ODOO_API_KEY
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD
  EMAIL_FROM, EMAIL_TO
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


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
TZ = ZoneInfo("Asia/Amman")
TGR_POS_CONFIG_ID = 3   # POS register id for Green Room / Dine-In


def env(name: str, required: bool = True, default: str | None = None) -> str | None:
    v = os.environ.get(name, default)
    if required and not v:
        sys.stderr.write(f"FATAL: env var {name} is not set\n")
        sys.exit(2)
    return v


ODOO_URL      = env("ODOO_URL")
ODOO_DB       = env("ODOO_DB")
ODOO_LOGIN    = env("ODOO_LOGIN")
ODOO_API_KEY  = env("ODOO_API_KEY")
SMTP_HOST     = env("SMTP_HOST", default="smtp.gmail.com")
SMTP_PORT     = int(env("SMTP_PORT", default="587"))
SMTP_USER     = env("SMTP_USER")
SMTP_PASSWORD = env("SMTP_PASSWORD")
EMAIL_FROM    = env("EMAIL_FROM")
EMAIL_TO      = env("EMAIL_TO")
# Optional — Cc recipients (comma-separated). Used to copy y.hamed@optico.jo
# on every send so the user has a record of what went out.
EMAIL_CC      = env("EMAIL_CC", required=False, default="")
# Optional — if the actual SMTP sender (Gmail) differs from the address you
# want replies to go to (y.hamed@optico.jo), set REPLY_TO accordingly.
REPLY_TO      = env("REPLY_TO", required=False, default="")


# -----------------------------------------------------------------------------
# Odoo client
# -----------------------------------------------------------------------------
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
    """Read-only wrapper. Refuse any non-read method."""
    if method not in {"read", "search", "search_read", "search_count"}:
        raise RuntimeError(f"Refused non-read method: {method}")
    return models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, model, method,
                              args, opts or {})


# -----------------------------------------------------------------------------
# Pull TGR stats for a given local-time date
# -----------------------------------------------------------------------------
def tgr_stats_for_day(target_date):
    uid, models = odoo_client()
    start_local = datetime.combine(target_date, datetime.min.time(), TZ)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    end_utc = end_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    orders = kw(models, uid, "pos.order", "search_read",
                [[["date_order", ">=", start_utc],
                  ["date_order", "<", end_utc],
                  ["state", "in", ["paid", "done", "invoiced"]],
                  ["config_id", "=", TGR_POS_CONFIG_ID]]],
                {"fields": ["name", "partner_id",
                            "amount_total", "amount_tax", "date_order"],
                 "limit": 10000})

    total_orders = len(orders)
    walk_in_orders = sum(1 for o in orders if not o.get("partner_id"))
    named_orders = total_orders - walk_in_orders

    customers = defaultdict(lambda: {"orders": 0, "net": 0.0})
    walk_in_net = 0.0
    for o in orders:
        net = float(o.get("amount_total") or 0) - float(o.get("amount_tax") or 0)
        if o.get("partner_id"):
            customers[o["partner_id"][1]]["orders"] += 1
            customers[o["partner_id"][1]]["net"] += net
        else:
            walk_in_net += net

    return {
        "date": target_date,
        "total_orders": total_orders,
        "walk_in_orders": walk_in_orders,
        "named_orders": named_orders,
        "unique_named": len(customers),
        "named_revenue_net": sum(c["net"] for c in customers.values()),
        "walk_in_revenue_net": walk_in_net,
        "top_named": sorted(customers.items(), key=lambda x: -x[1]["net"])[:10],
    }


# -----------------------------------------------------------------------------
# Email rendering
# -----------------------------------------------------------------------------
def fmt(n):
    return f"{n:,.0f}"


def build_html(s):
    rows = ""
    if s["top_named"]:
        for nm, c in s["top_named"]:
            rows += (
                f"<tr>"
                f"<td style='text-align:right;padding:6px 12px;color:#A1A1AA'>{c['orders']}</td>"
                f"<td style='text-align:right;padding:6px 12px;color:#F4F4F5;"
                f"font-variant-numeric:tabular-nums'>{fmt(c['net'])} JOD</td>"
                f"<td style='padding:6px 12px;color:#F4F4F5;direction:ltr;"
                f"text-align:left;unicode-bidi:embed'>&#x200E;{nm}</td>"
                f"</tr>"
            )
    else:
        rows = ("<tr><td colspan='3' style='padding:14px;text-align:center;"
                "color:#71717A'><i>No named-customer orders today.</i></td></tr>")

    total_net = s["named_revenue_net"] + s["walk_in_revenue_net"]
    date_label = s["date"].strftime("%A, %d %b %Y")

    return f"""
<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="background:#0A0A0B;font-family:'Segoe UI',Helvetica,Arial,sans-serif;
             color:#D4D4D8;padding:24px;margin:0">

  <div style="max-width:680px;margin:0 auto;background:#111114;
              border:1px solid #23232B;border-radius:14px;padding:28px 32px">

    <div style="color:#19E3B6;font-size:11px;font-weight:700;letter-spacing:0.18em;
                text-transform:uppercase;margin-bottom:6px">
      Fyxx TGR Daily Summary
    </div>
    <h1 style="color:#F4F4F5;font-size:22px;font-weight:700;margin:0 0 24px 0;
               letter-spacing:-0.01em">
      Green Room (Dine-In) · {date_label}
    </h1>

    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px">
      <div style="flex:1;min-width:160px;background:#15151A;border:1px solid #23232B;
                  border-radius:10px;padding:14px 16px">
        <div style="color:#71717A;font-size:11px;text-transform:uppercase;
                    letter-spacing:0.12em;margin-bottom:6px">Total orders</div>
        <div style="color:#F4F4F5;font-size:26px;font-weight:700;
                    font-variant-numeric:tabular-nums">{s['total_orders']:,}</div>
      </div>
      <div style="flex:1;min-width:160px;background:#15151A;border:1px solid #23232B;
                  border-radius:10px;padding:14px 16px">
        <div style="color:#71717A;font-size:11px;text-transform:uppercase;
                    letter-spacing:0.12em;margin-bottom:6px">Unique named customers</div>
        <div style="color:#19E3B6;font-size:26px;font-weight:700;
                    font-variant-numeric:tabular-nums">{s['unique_named']:,}</div>
      </div>
    </div>

    <table style="width:100%;border-collapse:collapse;margin-bottom:24px;
                  font-variant-numeric:tabular-nums">
      <tr>
        <td style="padding:9px 0;color:#A1A1AA">Orders to named customers</td>
        <td style="padding:9px 0;text-align:right;color:#F4F4F5;font-weight:600">
          {s['named_orders']:,}
        </td>
      </tr>
      <tr style="border-top:1px solid #1F1F26">
        <td style="padding:9px 0;color:#A1A1AA">Orders to walk-in (no name)</td>
        <td style="padding:9px 0;text-align:right;color:#F4F4F5;font-weight:600">
          {s['walk_in_orders']:,}
        </td>
      </tr>
      <tr style="border-top:1px solid #1F1F26">
        <td style="padding:9px 0;color:#A1A1AA">Net revenue · named customers</td>
        <td style="padding:9px 0;text-align:right;color:#F4F4F5;font-weight:600">
          {fmt(s['named_revenue_net'])} JOD
        </td>
      </tr>
      <tr style="border-top:1px solid #1F1F26">
        <td style="padding:9px 0;color:#A1A1AA">Net revenue · walk-in</td>
        <td style="padding:9px 0;text-align:right;color:#F4F4F5;font-weight:600">
          {fmt(s['walk_in_revenue_net'])} JOD
        </td>
      </tr>
      <tr style="border-top:1px solid #2A2A33;background:rgba(25,227,182,0.04)">
        <td style="padding:11px 0;color:#F4F4F5;font-weight:700">Total net revenue (excl. VAT)</td>
        <td style="padding:11px 0;text-align:right;color:#19E3B6;font-weight:700;
                   font-size:16px">{fmt(total_net)} JOD</td>
      </tr>
    </table>

    <h3 style="color:#A1A1AA;font-size:11px;text-transform:uppercase;
               letter-spacing:0.12em;font-weight:700;margin:0 0 8px 0">
      Top named customers today
    </h3>
    <table style="width:100%;border-collapse:collapse;background:#0E0E12;
                  border:1px solid #1F1F26;border-radius:10px;overflow:hidden">
      <thead>
        <tr style="background:#16161B">
          <th style="text-align:right;padding:8px 12px;color:#71717A;
                     font-size:10px;text-transform:uppercase;letter-spacing:0.10em">
            Orders
          </th>
          <th style="text-align:right;padding:8px 12px;color:#71717A;
                     font-size:10px;text-transform:uppercase;letter-spacing:0.10em">
            Net
          </th>
          <th style="text-align:left;padding:8px 12px;color:#71717A;
                     font-size:10px;text-transform:uppercase;letter-spacing:0.10em">
            Customer
          </th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>

    <div style="margin-top:24px;padding-top:16px;border-top:1px solid #1F1F26;
                color:#52525B;font-size:11px;text-align:center">
      Generated automatically by the Fyxx Insights pipeline ·
      {datetime.now(TZ).strftime('%Y-%m-%d %H:%M %Z')}
    </div>

  </div>
</body></html>
"""


def build_plain(s):
    lines = [
        f"Fyxx TGR Daily Customer Summary",
        f"Date: {s['date'].strftime('%A, %d %b %Y')}",
        "",
        f"Total POS orders at TGR:         {s['total_orders']:,}",
        f"  Orders to NAMED customers:     {s['named_orders']:,}",
        f"  Orders to WALK-IN (no name):   {s['walk_in_orders']:,}",
        "",
        f"Unique NAMED customers today:    {s['unique_named']:,}",
        "",
        f"Net revenue (excl. VAT) - TGR only:",
        f"  Named customers:        {fmt(s['named_revenue_net'])} JOD",
        f"  Walk-in:                {fmt(s['walk_in_revenue_net'])} JOD",
        f"  TOTAL:                  {fmt(s['named_revenue_net'] + s['walk_in_revenue_net'])} JOD",
        "",
    ]
    if s["top_named"]:
        lines.append("Top named customers today by net revenue:")
        for nm, c in s["top_named"]:
            lines.append(f"  {c['orders']:>3} order(s)   {fmt(c['net']):>9} JOD   {nm}")
    lines.append("")
    lines.append("Generated automatically by the Fyxx Insights pipeline.")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Send
# -----------------------------------------------------------------------------
def send_email(stats):
    subject = (f"Fyxx TGR Daily Summary — "
               f"{stats['date'].strftime('%d %b %Y')} "
               f"({stats['total_orders']} orders, "
               f"{stats['unique_named']} named customers)")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    if EMAIL_CC:
        msg["Cc"] = EMAIL_CC
    if REPLY_TO:
        msg["Reply-To"] = REPLY_TO

    msg.attach(MIMEText(build_plain(stats), "plain", "utf-8"))
    msg.attach(MIMEText(build_html(stats), "html", "utf-8"))

    to_list = [r.strip() for r in EMAIL_TO.split(",") if r.strip()]
    cc_list = [r.strip() for r in EMAIL_CC.split(",") if r.strip()] if EMAIL_CC else []
    all_recipients = to_list + cc_list

    print(f"Connecting to {SMTP_HOST}:{SMTP_PORT} as {SMTP_USER} ...")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(EMAIL_FROM, all_recipients, msg.as_string())
    cc_label = f" (cc {EMAIL_CC})" if EMAIL_CC else ""
    print(f"Sent to {EMAIL_TO}{cc_label} OK.")


def _resolve_target_date():
    """Return the date the report should cover.

    Defaults to TODAY in Asia/Amman. The optional TARGET_DATE env var lets
    operators re-send any historical day; values accepted:
      - YYYY-MM-DD literal (e.g. 2026-05-21)
      - 'today'      (same as default)
      - 'yesterday'  (today - 1)
    """
    today_local = datetime.now(TZ).date()
    raw = (os.environ.get("TARGET_DATE") or "").strip().lower()
    if not raw or raw == "today":
        return today_local, "today"
    if raw == "yesterday":
        return today_local - timedelta(days=1), "yesterday"
    try:
        d = datetime.strptime(raw, "%Y-%m-%d").date()
        return d, f"override={raw}"
    except ValueError:
        sys.stderr.write(f"WARN: ignoring invalid TARGET_DATE={raw!r}, "
                         f"falling back to today\n")
        return today_local, "today"


def main():
    target_date, label = _resolve_target_date()
    print(f"Target date (Asia/Amman): {target_date}  [{label}]")
    stats = tgr_stats_for_day(target_date)
    print(f"Stats: total={stats['total_orders']} "
          f"named={stats['named_orders']} walk_in={stats['walk_in_orders']} "
          f"unique={stats['unique_named']}")
    send_email(stats)


if __name__ == "__main__":
    main()
