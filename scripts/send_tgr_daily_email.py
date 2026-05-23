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
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO
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
# PDF rendering (reportlab — installed by the workflow)
# -----------------------------------------------------------------------------
def build_pdf(stats) -> bytes:
    """Render a single-page PDF that mirrors the email content."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle)

    ACCENT = colors.HexColor("#0F9D7B")
    DARK   = colors.HexColor("#111114")
    MID    = colors.HexColor("#52525B")
    LINE   = colors.HexColor("#E4E4E7")
    TINT   = colors.HexColor("#F4FBF8")

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=18*mm, bottomMargin=18*mm,
        title=f"Fyxx TGR Summary {stats['date']:%Y-%m-%d}",
        author="Fyxx Insights",
    )

    base = getSampleStyleSheet()
    eyebrow = ParagraphStyle("eyebrow", parent=base["Normal"],
        fontName="Helvetica-Bold", fontSize=9, textColor=ACCENT,
        leading=11, spaceAfter=2)
    title = ParagraphStyle("title", parent=base["Title"],
        fontName="Helvetica-Bold", fontSize=22, leading=26,
        textColor=DARK, alignment=0, spaceAfter=4)
    subtitle = ParagraphStyle("subtitle", parent=base["Normal"],
        fontSize=11, textColor=MID, spaceAfter=18)
    section = ParagraphStyle("section", parent=base["Normal"],
        fontName="Helvetica-Bold", fontSize=9, textColor=MID,
        leading=11, spaceBefore=14, spaceAfter=6)
    footer = ParagraphStyle("footer", parent=base["Normal"],
        fontSize=8, textColor=MID, alignment=1)

    elems = []
    elems.append(Paragraph("FYXX TGR DAILY SUMMARY", eyebrow))
    elems.append(Paragraph("Green Room (Dine-In)", title))
    elems.append(Paragraph(stats["date"].strftime("%A, %d %B %Y"), subtitle))

    # ---- KPI row ----
    kpi_left = (
        f'<font size="9" color="#52525B">TOTAL ORDERS</font><br/>'
        f'<font size="22" color="#111114"><b>{stats["total_orders"]:,}</b></font>'
    )
    kpi_right = (
        f'<font size="9" color="#52525B">UNIQUE NAMED CUSTOMERS</font><br/>'
        f'<font size="22" color="#0F9D7B"><b>{stats["unique_named"]:,}</b></font>'
    )
    kpi = Table(
        [[Paragraph(kpi_left, base["Normal"]),
          Paragraph(kpi_right, base["Normal"])]],
        colWidths=[82*mm, 82*mm],
    )
    kpi.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.5, LINE),
        ("LINEAFTER", (0,0), (0,0), 0.5, LINE),
        ("LEFTPADDING", (0,0), (-1,-1), 14),
        ("RIGHTPADDING", (0,0), (-1,-1), 14),
        ("TOPPADDING", (0,0), (-1,-1), 14),
        ("BOTTOMPADDING", (0,0), (-1,-1), 16),
    ]))
    elems.append(kpi)

    # ---- Breakdown table ----
    elems.append(Paragraph("BREAKDOWN", section))
    total_net = stats["named_revenue_net"] + stats["walk_in_revenue_net"]
    breakdown = [
        ["Orders to named customers",       f"{stats['named_orders']:,}"],
        ["Orders to walk-in (no name)",     f"{stats['walk_in_orders']:,}"],
        ["Net revenue · named customers",   f"{stats['named_revenue_net']:,.0f} JOD"],
        ["Net revenue · walk-in",           f"{stats['walk_in_revenue_net']:,.0f} JOD"],
        ["Total net revenue (excl. VAT)",   f"{total_net:,.0f} JOD"],
    ]
    bd = Table(breakdown, colWidths=[114*mm, 50*mm])
    bd.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), "Helvetica", 10),
        ("TEXTCOLOR", (0,0), (0,-1), MID),
        ("TEXTCOLOR", (1,0), (1,-2), DARK),
        ("ALIGN", (1,0), (1,-1), "RIGHT"),
        ("LINEBELOW", (0,0), (-1,-2), 0.25, LINE),
        ("BACKGROUND", (0,-1), (-1,-1), TINT),
        ("FONT", (0,-1), (-1,-1), "Helvetica-Bold", 10),
        ("TEXTCOLOR", (1,-1), (1,-1), ACCENT),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 8),
    ]))
    elems.append(bd)

    # ---- Top named customers ----
    if stats["top_named"]:
        elems.append(Paragraph("TOP NAMED CUSTOMERS", section))
        header = ["Orders", "Net Revenue", "Customer"]
        rows = [header]
        for nm, c in stats["top_named"]:
            rows.append([str(c["orders"]), f"{c['net']:,.0f} JOD", nm])
        tb = Table(rows, colWidths=[20*mm, 40*mm, 104*mm])
        tb.setStyle(TableStyle([
            ("FONT", (0,0), (-1,0), "Helvetica-Bold", 8),
            ("TEXTCOLOR", (0,0), (-1,0), MID),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#F4F4F5")),
            ("ALIGN", (0,0), (1,-1), "RIGHT"),
            ("ALIGN", (2,0), (2,-1), "LEFT"),
            ("FONT", (0,1), (-1,-1), "Helvetica", 10),
            ("TEXTCOLOR", (0,1), (-1,-1), DARK),
            ("LINEBELOW", (0,0), (-1,-1), 0.25, LINE),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
            ("RIGHTPADDING", (0,0), (-1,-1), 8),
            ("BOTTOMPADDING", (0,0), (-1,-1), 7),
            ("TOPPADDING", (0,0), (-1,-1), 7),
        ]))
        elems.append(tb)
    else:
        elems.append(Paragraph(
            "<i>No named-customer orders on this date.</i>",
            ParagraphStyle("empty", parent=base["Normal"],
                           fontSize=10, textColor=MID, spaceBefore=10)))

    elems.append(Spacer(1, 24))
    gen_at = datetime.now(TZ).strftime("%Y-%m-%d %H:%M %Z")
    elems.append(Paragraph(
        f"Generated automatically by Fyxx Insights · {gen_at}", footer))

    doc.build(elems)
    return buf.getvalue()


# -----------------------------------------------------------------------------
# Send
# -----------------------------------------------------------------------------
def send_email(stats):
    subject = (f"Fyxx TGR Daily Summary — "
               f"{stats['date'].strftime('%d %b %Y')} "
               f"({stats['total_orders']} orders, "
               f"{stats['unique_named']} named customers)")

    # Outer container is "mixed" so we can ride a PDF attachment alongside
    # the html/plain alternative pair.
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    if EMAIL_CC:
        msg["Cc"] = EMAIL_CC
    if REPLY_TO:
        msg["Reply-To"] = REPLY_TO

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(build_plain(stats), "plain", "utf-8"))
    alt.attach(MIMEText(build_html(stats), "html", "utf-8"))
    msg.attach(alt)

    # PDF attachment
    try:
        pdf_bytes = build_pdf(stats)
        pdf = MIMEApplication(pdf_bytes, _subtype="pdf")
        pdf_name = f"TGR-summary-{stats['date'].strftime('%Y-%m-%d')}.pdf"
        pdf.add_header("Content-Disposition", "attachment", filename=pdf_name)
        msg.attach(pdf)
        print(f"PDF attached: {pdf_name} ({len(pdf_bytes):,} bytes)")
    except Exception as e:
        # Don't fail the whole email if PDF generation hiccups — send w/o attachment
        sys.stderr.write(f"WARN: PDF generation failed, sending without attachment: {e}\n")

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
