"""Fyxx hosted-dashboard data exporter.

Pulls Odoo data (STRICTLY READ-ONLY: search / search_read / read /
search_count only), applies the exact same business rules as the
Streamlit app (app.py), and writes compact JSON files consumed by the
static dashboard at https://umg.jo/dashboard/fyxx/.

Run modes:
  python hosted/fyxx_export.py --no-upload      # local test, writes ./hosted/out
  python hosted/fyxx_export.py                  # export + FTP upload to /fyxx/data

Required env vars (or ~/.odoo-creds.env fallback for local runs):
  ODOO_URL, ODOO_DB, ODOO_LOGIN, ODOO_API_KEY
Upload additionally needs:
  FTP_HOST (default ftp3.ftptoyoursite.com), FTP_USER, FTP_PASSWORD

Python stdlib only — no third-party packages.
"""
from __future__ import annotations

import json
import os
import re
import sys
import xmlrpc.client
from collections import defaultdict
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Amman")

# =============================================================================
# Business rules — mirrored from app.py. Keep in sync.
# =============================================================================
_ECOM_SALESPERSON_KEYWORDS = ("shopify",)
_B2B_SALESPERSON_KEYWORDS = ("tareq", "yousef")
_B2C_COMPANY_KEYWORDS = ("fyxx operations (b2c)", "fyxx operations")
POS_CONFIG_CHANNEL_MAP = {3: "TGR", 2: "Retail", 5: "Retail", 6: "Retail",
                          7: "TGR",   # Roof WC → TGR
                          8: "TGR"}   # Restaurant → TGR
EXCLUDED_POS_CONFIG_IDS = [4]
_EXCLUDED_CUSTOMER_KEYWORDS = ("fyxx operations", "jt international")
_CUSTOMER_CHANNEL_OVERRIDES = ((("jordanian duty free", "duty free shops"), "DF"),)
SUPPLIER_ALIASES = (
    ("fyxx", "Fyxx"),
    ("union marketing", "UMG"), ("umg", "UMG"), ("optico", "UMG"),
    ("global brands", "UMG"), ("tafaol", "UMG"),
    ("bulos", "Zumot"), ("zumot", "Zumot"),
    ("arab italian", "Arab Italian"),
    ("yhc", "YHC"),
)


def resolve_channel_so(sp, co):
    sp = (sp or "").strip().lower()
    co = (co or "").strip().lower()
    if any(k in co for k in _B2C_COMPANY_KEYWORDS):
        if any(k in sp for k in _ECOM_SALESPERSON_KEYWORDS):
            return "E-com"
        if any(k in sp for k in _B2B_SALESPERSON_KEYWORDS):
            return "B2B"
    return "Retail"


def _customer_channel_override(name):
    if not name:
        return None
    low = str(name).strip().lower()
    for keywords, channel in _CUSTOMER_CHANNEL_OVERRIDES:
        if any(k in low for k in keywords):
            return channel
    return None


def _is_internal_customer(name):
    if not name:
        return False
    low = str(name).strip().lower()
    return any(k in low for k in _EXCLUDED_CUSTOMER_KEYWORDS)


def _is_retail_at_green_room(category_path):
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


def _normalise_supplier(name):
    if not name:
        return name
    low = str(name).strip().lower()
    for needle, canonical in SUPPLIER_ALIASES:
        if needle in low:
            return canonical
    return name


def _clean_product_name(name):
    if not name:
        return name
    return re.sub(r"^\s*\[[^\]]+\]\s*", "", str(name)).strip()


def _pnl_category_of(name):
    n = (name or "").lower()
    parent = n.split(":")[0].strip()
    return parent.title() if parent else (name or "Other")


# =============================================================================
# Env / Odoo client
# =============================================================================
def _load_env_file(path):
    env = {}
    p = Path(path)
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


_FILE_ENV = _load_env_file(Path.home() / ".odoo-creds.env")


def env(name, default=None, required=True):
    v = os.environ.get(name) or _FILE_ENV.get(name) or default
    if required and not v:
        sys.stderr.write(f"FATAL: env var {name} not set\n")
        sys.exit(2)
    return v


ODOO_URL = env("ODOO_URL").rstrip("/")
ODOO_DB = env("ODOO_DB")
ODOO_LOGIN = env("ODOO_LOGIN")
ODOO_API_KEY = env("ODOO_API_KEY")

_common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common", allow_none=True)
UID = _common.authenticate(ODOO_DB, ODOO_LOGIN, ODOO_API_KEY, {})
if not UID:
    sys.stderr.write("FATAL: Odoo authentication failed\n")
    sys.exit(2)
_models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object", allow_none=True)

_READ_ONLY = {"read", "search", "search_read", "search_count", "fields_get"}


def kw(model, method, args, opts=None):
    if method not in _READ_ONLY:
        raise RuntimeError(f"Refused non-read method: {method}")
    return _models.execute_kw(ODOO_DB, UID, ODOO_API_KEY, model, method,
                              args, opts or {})


# =============================================================================
# Helpers
# =============================================================================
def utc_str(dt_aware):
    return dt_aware.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def parse_odoo_ts(s):
    """'YYYY-MM-DD HH:MM:SS' (UTC) -> epoch seconds int."""
    return int(datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
               .replace(tzinfo=timezone.utc).timestamp())


def r2(x):
    return round(float(x or 0), 2)


class Interner:
    """String -> index dictionary builder for columnar JSON."""

    def __init__(self):
        self.map = {}
        self.list = []

    def idx(self, s):
        s = s if s is not None else "—"
        i = self.map.get(s)
        if i is None:
            i = len(self.list)
            self.map[s] = i
            self.list.append(s)
        return i


NOW = datetime.now(TZ)
HIST_START = datetime(NOW.year - 2, 1, 1, tzinfo=TZ)
START_ISO = utc_str(HIST_START)
END_ISO = utc_str(NOW)
print(f"Export window: {HIST_START:%Y-%m-%d} -> {NOW:%Y-%m-%d %H:%M} (Amman)")


# =============================================================================
# 1) Confirmed orders (sale.order + pos.order) with Green Room split
# =============================================================================
def fetch_orders():
    print("Fetching sale.order (confirmed)...")
    sos = kw("sale.order", "search_read",
             [[["date_order", ">=", START_ISO], ["date_order", "<=", END_ISO],
               ["state", "in", ["sale", "done"]]]],
             {"fields": ["name", "partner_id", "user_id", "company_id",
                         "amount_untaxed", "amount_tax", "date_order", "margin",
                         "state"],
              "limit": 200000, "order": "date_order asc"})
    print(f"  sale.order rows: {len(sos)}")

    print("Fetching pos.order (confirmed)...")
    poss = kw("pos.order", "search_read",
              [[["date_order", ">=", START_ISO], ["date_order", "<=", END_ISO],
                ["state", "in", ["paid", "done", "invoiced"]],
                ["config_id", "not in", EXCLUDED_POS_CONFIG_IDS]]],
              {"fields": ["name", "partner_id", "user_id", "config_id",
                          "amount_total", "amount_tax", "date_order", "margin",
                          "state"],
               "limit": 200000, "order": "date_order asc"})
    print(f"  pos.order rows: {len(poss)}")

    rows = []
    for o in sos:
        customer = o["partner_id"][1] if o.get("partner_id") else "—"
        salesperson = o["user_id"][1] if o.get("user_id") else "—"
        company = o["company_id"][1] if o.get("company_id") else None
        rows.append({
            "order_id": o["id"], "name": o.get("name") or "",
            "ts": parse_odoo_ts(o["date_order"]),
            "channel": resolve_channel_so(salesperson, company),
            "customer": customer, "salesperson": salesperson,
            "amount": float(o.get("amount_untaxed") or 0),
            "vat": float(o.get("amount_tax") or 0),
            "margin": float(o.get("margin") or 0),
            "source": 0, "pos": False, "state": o.get("state") or "sale",
        })
    for o in poss:
        cid = o["config_id"][0] if o.get("config_id") else None
        channel = POS_CONFIG_CHANNEL_MAP.get(
            cid, o["config_id"][1] if o.get("config_id") else "POS")
        customer = o["partner_id"][1] if o.get("partner_id") else "Walk-in"
        salesperson = o["user_id"][1] if o.get("user_id") else "—"
        net = (o.get("amount_total") or 0) - (o.get("amount_tax") or 0)
        rows.append({
            "order_id": o["id"], "name": o.get("name") or "",
            "ts": parse_odoo_ts(o["date_order"]),
            "channel": channel, "customer": customer,
            "salesperson": salesperson, "amount": net,
            "vat": float(o.get("amount_tax") or 0),
            "margin": float(o.get("margin") or 0),
            "source": 1, "pos": True, "state": o.get("state") or "paid",
        })

    rows = [r for r in rows if not _is_internal_customer(r["customer"])]
    for r in rows:
        ov = _customer_channel_override(r["customer"])
        if ov:
            r["channel"] = ov
    return split_green_room(rows)


def _product_categories(pids):
    out = {}
    pids = list(pids)
    for i in range(0, len(pids), 1000):
        try:
            for r in kw("product.product", "read", [pids[i:i + 1000]],
                        {"fields": ["id", "categ_id"]}):
                out[r["id"]] = (r["categ_id"][1] if r.get("categ_id") else "") or ""
        except Exception:
            pass
    return out


def split_green_room(rows):
    gr = [(i, r) for i, r in enumerate(rows)
          if r["pos"] and r["channel"] == "TGR"]
    gr_ids = [r["order_id"] for _, r in gr]
    print(f"Green Room orders to split: {len(gr_ids)}")
    if not gr_ids:
        return rows
    lines = []
    for i in range(0, len(gr_ids), 2000):
        try:
            lines += kw("pos.order.line", "search_read",
                        [[["order_id", "in", gr_ids[i:i + 2000]]]],
                        {"fields": ["order_id", "product_id",
                                    "price_subtotal", "margin"],
                         "limit": 500000})
        except Exception:
            pass
    print(f"  GR lines: {len(lines)}")
    cats = _product_categories({l["product_id"][0] for l in lines
                                if l.get("product_id")})
    splits = defaultdict(lambda: {"rn": 0.0, "dn": 0.0, "rm": 0.0, "dm": 0.0})
    for l in lines:
        if not l.get("order_id") or not l.get("product_id"):
            continue
        oid = l["order_id"][0]
        path = cats.get(l["product_id"][0], "")
        net = float(l.get("price_subtotal") or 0)
        mg = float(l.get("margin") or 0)
        if _is_retail_at_green_room(path):
            splits[oid]["rn"] += net
            splits[oid]["rm"] += mg
        else:
            splits[oid]["dn"] += net
            splits[oid]["dm"] += mg

    gr_index = {i for i, _ in gr}
    out = []
    for i, r in enumerate(rows):
        if i not in gr_index:
            out.append(r)
            continue
        s = splits.get(r["order_id"])
        total = (s["rn"] + s["dn"]) if s else 0
        if not s or total <= 0:
            out.append(r)
            continue
        vat = r["vat"]
        if s["rn"] > 0:
            out.append({**r, "channel": "Retail", "amount": s["rn"],
                        "vat": vat * s["rn"] / total, "margin": s["rm"]})
        if s["dn"] > 0:
            out.append({**r, "channel": "TGR", "amount": s["dn"],
                        "vat": vat * s["dn"] / total, "margin": s["dm"]})
    return out


# =============================================================================
# 2) Draft / sent / cancelled sale.orders (Shifts tab extras)
# =============================================================================
def fetch_states():
    print("Fetching draft/sent/cancel sale.orders...")
    rows = kw("sale.order", "search_read",
              [[["date_order", ">=", START_ISO], ["date_order", "<=", END_ISO],
                ["state", "in", ["draft", "sent", "cancel"]]]],
              {"fields": ["state", "date_order", "user_id", "company_id",
                          "partner_id"],
               "limit": 200000})
    print(f"  rows: {len(rows)}")
    smap = {"draft": 0, "sent": 1, "cancel": 2}
    out = []
    for o in rows:
        customer = o["partner_id"][1] if o.get("partner_id") else "—"
        if _is_internal_customer(customer):
            continue
        sp = o["user_id"][1] if o.get("user_id") else "—"
        co = o["company_id"][1] if o.get("company_id") else None
        ch = _customer_channel_override(customer) or resolve_channel_so(sp, co)
        out.append((parse_odoo_ts(o["date_order"]), ch, smap[o["state"]]))
    return out


# =============================================================================
# 3) Delivery orders (real deliveries only)
# =============================================================================
def fetch_deliveries():
    print("Fetching delivery orders...")
    try:
        ptypes = kw("stock.picking.type", "search_read",
                    [[["code", "=", "outgoing"]]],
                    {"fields": ["name"], "limit": 100})
    except Exception:
        return []
    ids = [p["id"] for p in ptypes if p.get("name") == "Delivery Orders"]
    if not ids:
        return []
    pks = kw("stock.picking", "search_read",
             [[["picking_type_id", "in", ids],
               ["sale_id.date_order", ">=", START_ISO],
               ["sale_id.date_order", "<=", END_ISO]]],
             {"fields": ["state", "sale_id", "date_done", "carrier_id"],
              "limit": 200000})
    print(f"  pickings: {len(pks)}")
    sids = list({p["sale_id"][0] for p in pks if p.get("sale_id")})
    so = {}
    for i in range(0, len(sids), 500):
        try:
            for s in kw("sale.order", "search_read",
                        [[["id", "in", sids[i:i + 500]]]],
                        {"fields": ["date_order", "user_id", "company_id",
                                    "partner_id"], "limit": 200000}):
                so[s["id"]] = s
        except Exception:
            pass
    smap = {"done": 0, "assigned": 1, "confirmed": 1, "waiting": 1, "cancel": 2}
    out = []
    for p in pks:
        sid = p["sale_id"][0] if p.get("sale_id") else None
        s = so.get(sid)
        if not s:
            continue
        cust = s["partner_id"][1] if s.get("partner_id") else "—"
        if _is_internal_customer(cust):
            continue
        sp = s["user_id"][1] if s.get("user_id") else "—"
        co = s["company_id"][1] if s.get("company_id") else None
        ch = _customer_channel_override(cust) or resolve_channel_so(sp, co)
        ots = parse_odoo_ts(s["date_order"])
        dts = parse_odoo_ts(p["date_done"]) if p.get("date_done") else None
        carrier = (p.get("carrier_id") or [0, "(none)"])[1]
        st = smap.get(p["state"])
        if st is None:
            continue
        out.append((ots, dts, st, carrier, ch))
    return out


# =============================================================================
# 4) Order lines (full line-level export, matched to orders via src+order_id)
# =============================================================================
def fetch_lines():
    """Return (lines, pinfo).

    lines: list of (src, order_id, product_id, qty, revenue, margin)
      src 0 = Sales Order, 1 = POS Ticket — matches orders.json src, so
      the front-end can filter lines by the channel-filtered order set
      exactly like app.py's (source, order_id) membership trick.
    pinfo: pid -> (name, subcategory w/ Spirits rollup, group, supplier)
    """
    print("Fetching order lines (full)...")
    lines = []
    pids = set()

    q_start = HIST_START
    while q_start < NOW:
        q_end = min(q_start + timedelta(days=92), NOW)
        try:
            batch = kw("sale.order.line", "search_read",
                       [[["order_id.date_order", ">=", utc_str(q_start)],
                         ["order_id.date_order", "<", utc_str(q_end)],
                         ["order_id.state", "in", ["sale", "done"]]]],
                       {"fields": ["product_id", "product_uom_qty",
                                   "price_subtotal", "margin", "order_id"],
                        "limit": 500000})
        except Exception:
            batch = []
        for l in batch:
            if not l.get("product_id") or not l.get("order_id"):
                continue
            pid = l["product_id"][0]
            pids.add(pid)
            lines.append((0, l["order_id"][0], pid,
                          r2(l.get("product_uom_qty")),
                          r2(l.get("price_subtotal")), r2(l.get("margin"))))
        q_start = q_end

    m_start = HIST_START
    while m_start < NOW:
        m_end = min(m_start + timedelta(days=31), NOW)
        try:
            batch = kw("pos.order.line", "search_read",
                       [[["order_id.date_order", ">=", utc_str(m_start)],
                         ["order_id.date_order", "<", utc_str(m_end)],
                         ["order_id.state", "in", ["paid", "done", "invoiced"]],
                         ["order_id.config_id", "not in",
                          EXCLUDED_POS_CONFIG_IDS]]],
                       {"fields": ["product_id", "qty", "price_subtotal",
                                   "margin", "order_id"],
                        "limit": 500000})
        except Exception:
            batch = []
        for l in batch:
            if not l.get("product_id") or not l.get("order_id"):
                continue
            pid = l["product_id"][0]
            pids.add(pid)
            lines.append((1, l["order_id"][0], pid,
                          r2(l.get("qty")),
                          r2(l.get("price_subtotal")), r2(l.get("margin"))))
        m_start = m_end
    print(f"  lines: {len(lines)}   products: {len(pids)}")

    pinfo = {}
    plist = list(pids)
    for i in range(0, len(plist), 1000):
        chunk = plist[i:i + 1000]
        try:
            recs = kw("product.product", "read", [chunk],
                      {"fields": ["id", "name", "categ_id",
                                  "x_studio_vendor_tags"]})
        except Exception:
            try:
                recs = kw("product.product", "read", [chunk],
                          {"fields": ["id", "name", "categ_id"]})
            except Exception:
                recs = []
        for r in recs:
            path = (r["categ_id"][1] if r.get("categ_id") else "") or ""
            parts = [p.strip() for p in path.split("/") if p.strip()]
            if parts and parts[0].lower() == "all":
                parts = parts[1:]
            if parts and any(seg.lower() == "spirits" for seg in parts[:-1]):
                sub = "Spirits"
            elif parts:
                sub = parts[-1]
            else:
                sub = "—"
            group = parts[0] if parts else "—"
            raw = r.get("x_studio_vendor_tags")
            supplier = (_normalise_supplier(str(raw).strip())
                        if raw else "No vendor tag")
            pinfo[r["id"]] = (_clean_product_name(r.get("name")), sub,
                              group, supplier)
    return lines, pinfo


# =============================================================================
# 5) P&L expense lines — per (day, account) so ANY window is exact
# =============================================================================
def fetch_pnl():
    """Returns (rows, accounts).
    rows: (dayKey 'YYYY-MM-DD', accountIdx, amount) aggregated per day+account
    accounts: [{code, name, type}] — front-end applies the same COGS-skip,
    depreciation and Parent:Child bucket rules as app.py."""
    print("Fetching P&L expense balances...")
    try:
        accs = kw("account.account", "search_read", [[]],
                  {"fields": ["id", "name", "code", "account_type"],
                   "limit": 5000})
    except Exception:
        return [], []
    exp = {a["id"]: a for a in accs
           if "expense" in str(a.get("account_type") or "").lower()}
    if not exp:
        return [], []
    try:
        lines = kw("account.move.line", "search_read",
                   [[["account_id", "in", list(exp.keys())],
                     ["date", ">=", HIST_START.strftime("%Y-%m-%d")],
                     ["date", "<=", NOW.strftime("%Y-%m-%d")],
                     ["parent_state", "=", "posted"]]],
                   {"fields": ["account_id", "debit", "credit", "date"],
                    "limit": 500000})
    except Exception:
        lines = []
    print(f"  expense move lines: {len(lines)}")
    aid_list = sorted(exp.keys())
    aid_idx = {aid: i for i, aid in enumerate(aid_list)}
    agg = defaultdict(float)   # (day, accIdx) -> signed amount
    for l in lines:
        if not l.get("account_id") or not l.get("date"):
            continue
        aid = l["account_id"][0]
        if aid not in aid_idx:
            continue
        day = str(l["date"])[:10]
        agg[(day, aid_idx[aid])] += (float(l.get("debit") or 0)
                                     - float(l.get("credit") or 0))
    rows = [(d, a, r2(v)) for (d, a), v in sorted(agg.items())
            if abs(v) >= 0.005]
    accounts = [{"code": exp[aid].get("code") or "",
                 "name": exp[aid].get("name") or "",
                 "type": exp[aid].get("account_type") or ""}
                for aid in aid_list]
    return rows, accounts


# =============================================================================
# Serialize
# =============================================================================
def build_files():
    files = {}

    orders = fetch_orders()
    ch_i, cu_i, sp_i, st_i = Interner(), Interner(), Interner(), Interner()
    o_ts, o_ch, o_cu, o_sp, o_amt, o_vat, o_mg, o_src = [], [], [], [], [], [], [], []
    o_nm, o_oid, o_st = [], [], []
    for r in sorted(orders, key=lambda x: x["ts"]):
        o_ts.append(r["ts"])
        o_ch.append(ch_i.idx(r["channel"]))
        o_cu.append(cu_i.idx(r["customer"]))
        o_sp.append(sp_i.idx(r["salesperson"]))
        o_amt.append(r2(r["amount"]))
        o_vat.append(r2(r["vat"]))
        o_mg.append(r2(r["margin"]))
        o_src.append(r["source"])
        o_nm.append(r["name"])
        o_oid.append(r["order_id"])
        o_st.append(st_i.idx(r["state"]))
    files["orders.json"] = {
        "ts": o_ts, "ch": o_ch, "cu": o_cu, "sp": o_sp,
        "amt": o_amt, "vat": o_vat, "mg": o_mg, "src": o_src,
        "nm": o_nm, "oid": o_oid, "st": o_st,
        "channels": ch_i.list, "customers": cu_i.list,
        "salespeople": sp_i.list, "states": st_i.list,
    }

    states = fetch_states()
    files["sostates.json"] = {
        "ts": [s[0] for s in states],
        "ch": [ch_i.idx(s[1]) for s in states],
        "st": [s[2] for s in states],
        "channels": ch_i.list,
    }

    dlv = fetch_deliveries()
    car_i = Interner()
    files["delivery.json"] = {
        "ots": [d[0] for d in dlv],
        "dts": [d[1] for d in dlv],
        "st": [d[2] for d in dlv],
        "car": [car_i.idx(d[3]) for d in dlv],
        "ch": [ch_i.idx(d[4]) for d in dlv],
        "carriers": car_i.list,
        "channels": ch_i.list,
    }

    lines, pinfo = fetch_lines()
    p_i = Interner()
    l_src, l_oid, l_p, l_q, l_r, l_g = [], [], [], [], [], []
    for (src, oid, pid, q, rev, mg) in lines:
        if pid not in pinfo:
            continue
        l_src.append(src)
        l_oid.append(oid)
        l_p.append(p_i.idx(pid))
        l_q.append(q)
        l_r.append(rev)
        l_g.append(mg)
    files["lines.json"] = {
        "src": l_src, "oid": l_oid, "p": l_p,
        "q": l_q, "r": l_r, "g": l_g,
        "products": [
            {"n": pinfo[pid][0], "c": pinfo[pid][1], "g": pinfo[pid][2],
             "s": pinfo[pid][3]}
            for pid in p_i.list
        ],
    }

    pnl_rows, pnl_accounts = fetch_pnl()
    files["pnl.json"] = {"rows": pnl_rows, "accounts": pnl_accounts}

    files["meta.json"] = {
        "generated_at": NOW.strftime("%Y-%m-%d %H:%M:%S"),
        "generated_at_ts": int(NOW.timestamp()),
        "window_start": HIST_START.strftime("%Y-%m-%d"),
        "window_end": NOW.strftime("%Y-%m-%d"),
        "orders": len(o_ts),
        "tz": "Asia/Amman",
        "currency": "JOD",
    }
    return files


def upload(files_written):
    import ftplib
    host = env("FTP_HOST", default="ftp3.ftptoyoursite.com")
    user = env("FTP_USER")
    pw = env("FTP_PASSWORD")
    print(f"Uploading {len(files_written)} files to {host} ...")
    ftp = ftplib.FTP(host, timeout=120)
    ftp.login(user, pw)
    for d in ("fyxx", "fyxx/data"):
        try:
            ftp.mkd(d)
        except ftplib.error_perm:
            pass
    for path in files_written:
        name = Path(path).name
        with open(path, "rb") as fh:
            ftp.storbinary(f"STOR fyxx/data/{name}", fh)
        print(f"  uploaded {name}")
    ftp.quit()
    print("Upload complete.")


def main():
    no_upload = "--no-upload" in sys.argv
    outdir = Path(__file__).parent / "out"
    outdir.mkdir(exist_ok=True)
    files = build_files()
    written = []
    for name, obj in files.items():
        p = outdir / name
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, separators=(",", ":"), ensure_ascii=False)
        sz = p.stat().st_size
        print(f"wrote {name}  {sz/1024:.0f} KB")
        written.append(str(p))
    if not no_upload:
        upload(written)
    print("DONE.")


if __name__ == "__main__":
    main()
