"""
Fyxx Executive Insights — live, read-only dashboard.

Companion to https://fyxx-sales.streamlit.app (operational view).
This app is the executive / strategic view: multi-year KPIs, historical
trends, channel mix, top movers — all rendered on a dark, editorial
canvas with neon accents.

Data source: Odoo XMLRPC. 100% READ-ONLY (search_read only).
"""
import os
import base64
import textwrap
import xmlrpc.client
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import hmac
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh


# =============================================================================
# DESIGN SYSTEM — dark editorial with neon accents
# =============================================================================
PALETTE = {
    "bg":        "#0A0A0B",   # page
    "surface":   "#111114",   # cards
    "surface2":  "#16161B",   # nested cards
    "border":    "#23232B",
    "border_lt": "#2D2D37",
    "text":      "#F4F4F5",   # primary
    "text_dim":  "#A1A1AA",   # secondary
    "muted":     "#71717A",   # tertiary

    "neon":      "#19E3B6",   # primary neon teal
    "neon_soft": "#0EA88B",
    "amber":     "#F5B544",   # warm secondary
    "rose":      "#EC4899",
    "violet":    "#A78BFA",
    "sky":       "#38BDF8",

    "good":      "#22C55E",
    "bad":       "#F87171",
}

# Year colors used in multi-year line charts (R G B-ish like the reference shot)
YEAR_COLORS = ["#38BDF8", "#22C55E", "#EC4899", "#F5B544", "#A78BFA", "#19E3B6"]

CHART_COLORWAY = [
    "#19E3B6", "#F5B544", "#A78BFA", "#38BDF8",
    "#EC4899", "#22C55E", "#F87171", "#FBBF24",
]


def _logo_data_uri():
    p = Path(__file__).parent / "assets" / "fyxx-logo.png"
    if not p.exists():
        return None
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()


CUSTOM_CSS = """
<style>
/* Hide streamlit chrome */
#MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; }

/* Page background */
.stApp { background: radial-gradient(1200px 600px at 80% -10%, rgba(25,227,182,0.06), transparent 60%), #0A0A0B; }
.block-container { padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1480px; }

/* Typography */
html, body, [class*="css"] {
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: #F4F4F5;
}
h1, h2, h3, h4 {
    color: #F4F4F5;
    letter-spacing: -0.02em;
    font-weight: 700;
}
h1 { font-size: 30px !important; }
h2 { font-size: 18px !important; font-weight: 600 !important; color: #E4E4E7 !important; }
h3 { font-size: 14px !important; font-weight: 600 !important; color: #A1A1AA !important;
     text-transform: uppercase; letter-spacing: 0.08em; }

/* Sidebar */
section[data-testid="stSidebar"] {
    background-color: #0E0E11;
    border-right: 1px solid #1F1F26;
}
section[data-testid="stSidebar"] .block-container { padding-top: 1.2rem; }

/* Inputs */
[data-testid="stTextInput"] input,
[data-baseweb="select"] > div,
[data-testid="stDateInput"] input {
    background-color: #15151A !important;
    color: #F4F4F5 !important;
    border: 1px solid #2A2A33 !important;
    border-radius: 10px !important;
}

/* KPI metric (we use custom cards but keep this for fallback) */
[data-testid="stMetric"] {
    background: linear-gradient(160deg, #131318 0%, #0F0F13 100%);
    border: 1px solid #23232B;
    border-radius: 16px;
    padding: 18px 22px;
}

/* Buttons */
.stButton > button {
    border-radius: 10px;
    border: 1px solid #2A2A33;
    background: #15151A;
    color: #F4F4F5;
    font-weight: 500;
    transition: all 0.15s ease;
}
.stButton > button:hover {
    border-color: #19E3B6;
    color: #19E3B6;
    background: #0F0F13;
}

/* Pills / segmented control */
button[kind="segmented_control"],
button[kind="pills"],
[data-testid="stPills"] button,
[data-testid="stSegmentedControl"] button {
    background: #15151A !important;
    color: #A1A1AA !important;
    border: 1px solid #2A2A33 !important;
    border-radius: 999px !important;
    font-weight: 500 !important;
    transition: all 0.15s ease !important;
    padding: 6px 14px !important;
}
button[kind="segmented_control"]:hover,
button[kind="pills"]:hover,
[data-testid="stPills"] button:hover,
[data-testid="stSegmentedControl"] button:hover {
    border-color: #19E3B6 !important;
    color: #19E3B6 !important;
}
button[kind="segmented_control"][aria-pressed="true"],
button[kind="pills"][aria-pressed="true"],
[data-testid="stPills"] button[aria-pressed="true"],
[data-testid="stSegmentedControl"] button[aria-pressed="true"] {
    background: #19E3B6 !important;
    color: #07221C !important;
    border-color: #19E3B6 !important;
    box-shadow: 0 0 16px rgba(25,227,182,0.35) !important;
    font-weight: 600 !important;
}
[data-testid="stMultiSelect"] [data-baseweb="tag"] {
    background-color: #19E3B6 !important;
    color: #07221C !important;
    border-radius: 6px !important;
}
/* Date input range */
[data-testid="stDateInput"] input {
    background-color: #15151A !important;
    color: #F4F4F5 !important;
    border: 1px solid #2A2A33 !important;
    border-radius: 10px !important;
}

/* Tabs */
[data-baseweb="tab-list"] {
    gap: 6px;
    border-bottom: 1px solid #1F1F26;
}
[data-baseweb="tab"] {
    background: transparent !important;
    color: #A1A1AA !important;
    font-weight: 600 !important;
    padding: 8px 18px !important;
    border-radius: 8px 8px 0 0 !important;
}
[data-baseweb="tab"][aria-selected="true"] {
    color: #19E3B6 !important;
    border-bottom: 2px solid #19E3B6 !important;
}

/* DataFrames */
[data-testid="stDataFrame"] {
    border-radius: 12px;
    border: 1px solid #23232B;
    overflow: hidden;
    background: #111114;
}

/* Dividers */
hr { margin: 1.2rem 0 !important; border-color: #1F1F26 !important; opacity: 1 !important; }

/* ----- custom components ----- */
.fyxx-logo {
    display: flex;
    align-items: center;
    justify-content: center;
    background: #000;
    border-radius: 14px;
    padding: 22px 0;
    border: 1px solid #1F1F26;
    margin-bottom: 6px;
}
.fyxx-logo img { width: 92px; height: auto; }
.brand-tag {
    text-align: center;
    color: #71717A;
    font-size: 10.5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    margin-bottom: 16px;
}
.live-pill {
    display: inline-flex; align-items: center; gap: 8px;
    background: rgba(25,227,182,0.08);
    color: #19E3B6;
    border: 1px solid rgba(25,227,182,0.3);
    padding: 5px 12px;
    border-radius: 999px;
    font-size: 11.5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
.live-dot {
    width: 7px; height: 7px;
    background-color: #19E3B6;
    border-radius: 50%;
    animation: pulse 1.8s infinite;
}
@keyframes pulse {
    0% { box-shadow: 0 0 0 0 rgba(25,227,182, 0.7); }
    70% { box-shadow: 0 0 0 9px rgba(25,227,182, 0); }
    100% { box-shadow: 0 0 0 0 rgba(25,227,182, 0); }
}

/* ===== Stock-news ticker bar ===== */
.ticker-bar {
    display: flex;
    align-items: stretch;
    background: linear-gradient(90deg,
        #08080A 0%,
        #101015 50%,
        #08080A 100%);
    border: 1px solid #1F1F26;
    border-radius: 14px;
    overflow: hidden;
    height: 46px;
    margin: 4px 0 14px 0;
    position: relative;
    box-shadow: 0 0 26px -10px rgba(25,227,182, 0.22),
                inset 0 0 0 1px rgba(25,227,182, 0.04);
}
.ticker-live {
    flex-shrink: 0;
    background: linear-gradient(90deg,
        rgba(25,227,182,0.16) 0%,
        rgba(25,227,182,0.04) 100%);
    border-right: 1px solid rgba(25,227,182, 0.30);
    display: flex; align-items: center; gap: 9px;
    padding: 0 18px;
    color: #19E3B6;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.20em;
    text-transform: uppercase;
    z-index: 2;
}
.ticker-live .dot {
    width: 7px; height: 7px;
    background: #19E3B6;
    border-radius: 50%;
    box-shadow: 0 0 8px #19E3B6;
    animation: pulse 1.8s infinite;
}
.ticker-mask {
    flex: 1;
    overflow: hidden;
    position: relative;
    -webkit-mask-image: linear-gradient(90deg, transparent 0%, #000 4%, #000 96%, transparent 100%);
            mask-image: linear-gradient(90deg, transparent 0%, #000 4%, #000 96%, transparent 100%);
}
.ticker-track {
    display: flex;
    align-items: center;
    height: 100%;
    width: max-content;
    animation: ticker-scroll 80s linear infinite;
}
.ticker-track:hover { animation-play-state: paused; }
@keyframes ticker-scroll {
    0%   { transform: translateX(0); }
    100% { transform: translateX(-50%); }
}
.ticker-item {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 0 28px;
    font-size: 12.5px;
    white-space: nowrap;
    border-right: 1px solid #1F1F26;
    height: 100%;
}
.ticker-item .label {
    color: #19E3B6;
    font-weight: 700;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    font-size: 10.8px;
    opacity: 0.92;
}
.ticker-item .value {
    color: #F4F4F5;
    font-weight: 600;
    letter-spacing: -0.005em;
}
.ticker-item .delta {
    font-weight: 700;
    font-size: 11.5px;
    padding: 2px 8px;
    border-radius: 999px;
    margin-left: 2px;
}
.ticker-item .delta.up {
    color: #BBF7D0;
    background: rgba(34,197,94, 0.12);
    border: 1px solid rgba(34,197,94, 0.30);
}
.ticker-item .delta.dn {
    color: #FECACA;
    background: rgba(248,113,113, 0.12);
    border: 1px solid rgba(248,113,113, 0.30);
}
.ticker-item .delta.flat {
    color: #A1A1AA;
    background: rgba(161,161,170, 0.10);
    border: 1px solid rgba(161,161,170, 0.25);
}

/* Hero */
.hero {
    display: flex; align-items: center; justify-content: space-between;
    gap: 18px; flex-wrap: wrap;
    padding-bottom: 14px;
    border-bottom: 1px solid #1F1F26;
    margin-bottom: 22px;
}
.hero-left {
    display: flex; align-items: center; gap: 18px;
}
.hero-logo {
    background: #000;
    border: 1px solid #1F1F26;
    border-radius: 12px;
    padding: 10px 18px;
    height: 56px;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
}
.hero-logo img { height: 32px; width: auto; display: block; }
.hero-eyebrow {
    color: #71717A; font-size: 11.5px; text-transform: uppercase;
    letter-spacing: 0.18em; font-weight: 600; margin-bottom: 6px;
}
.hero h1 { margin: 0; font-size: 30px !important; line-height: 1.15; }
.hero-accent { color: #19E3B6; }

/* KPI cards (custom — richer than st.metric) */
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }
.kpi {
    background: linear-gradient(160deg, #131318 0%, #0E0E12 100%);
    border: 1px solid #23232B;
    border-radius: 16px;
    padding: 18px 20px 16px 20px;
    position: relative;
    overflow: hidden;
}
.kpi::before {
    content: ""; position: absolute; left: 0; top: 0; bottom: 0;
    width: 2.5px;
    background: linear-gradient(180deg,
        rgba(25,227,182,0.32),
        rgba(25,227,182,0.08));
    border-radius: 0 2px 2px 0;
}
.kpi::after {
    content: "";
    position: absolute;
    left: 0;
    width: 2.5px;
    height: 36%;
    background: linear-gradient(180deg,
        transparent 0%,
        rgba(25,227,182,0.45) 25%,
        #19E3B6 50%,
        rgba(25,227,182,0.45) 75%,
        transparent 100%);
    border-radius: 2px;
    box-shadow: 0 0 12px 1.5px rgba(25,227,182,0.55),
                0 0 22px 0 rgba(25,227,182,0.25);
    filter: blur(0.3px);
    animation: kpi-beam 3.8s cubic-bezier(0.42, 0.0, 0.25, 1) infinite;
    pointer-events: none;
    z-index: 1;
}
@keyframes kpi-beam {
    0%   { top: -36%; opacity: 0; }
    10%  { opacity: 1; }
    90%  { opacity: 1; }
    100% { top: 100%; opacity: 0; }
}
/* Stagger the beam across the 4 KPI cards in the grid for a cascade feel */
.kpi-grid .kpi:nth-of-type(1)::after { animation-delay: 0s;    }
.kpi-grid .kpi:nth-of-type(2)::after { animation-delay: 0.55s; }
.kpi-grid .kpi:nth-of-type(3)::after { animation-delay: 1.10s; }
.kpi-grid .kpi:nth-of-type(4)::after { animation-delay: 1.65s; }
.kpi-grid .kpi:nth-of-type(5)::after { animation-delay: 2.20s; }
.kpi-label {
    color: #71717A; font-size: 10.5px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.14em; margin-bottom: 10px;
}
.kpi-value {
    color: #F4F4F5; font-size: 26px; font-weight: 700; line-height: 1.1;
    letter-spacing: -0.02em;
}
.kpi-value-sm { font-size: 20px; }
.kpi-sub {
    margin-top: 8px; font-size: 12px; color: #A1A1AA;
}
.kpi-delta-up { color: #22C55E; font-weight: 600; }
.kpi-delta-dn { color: #F87171; font-weight: 600; }
.kpi-foot {
    margin-top: 10px; padding-top: 10px;
    border-top: 1px solid #1F1F26;
    font-size: 11.5px; color: #71717A;
}

/* Year-performance card variant */
.year-card {
    background: linear-gradient(160deg, #14141A 0%, #0E0E13 100%);
    border: 1px solid #2A2A35;
    border-radius: 18px;
    padding: 22px 24px;
    position: relative;
    overflow: hidden;
}
.year-card .year-label {
    color: #A1A1AA; font-size: 12px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.12em;
}
.year-card .year-value {
    color: #F4F4F5; font-size: 32px; font-weight: 700;
    margin-top: 8px; letter-spacing: -0.02em;
}
.year-card .year-meta {
    color: #A1A1AA; font-size: 12.5px; margin-top: 14px; line-height: 1.7;
}
.year-card.is-current {
    border-color: rgba(25,227,182,0.45);
    animation: yc-breathe 4.2s ease-in-out infinite;
}
.year-card.is-current::after {
    content: ""; position: absolute; right: -50px; top: -50px;
    width: 180px; height: 180px;
    background: radial-gradient(closest-side, rgba(25,227,182,0.18), transparent 70%);
    transform-origin: 50% 50%;
    animation: yc-glow 4.2s ease-in-out infinite;
    pointer-events: none;
}
.year-card.is-current::before {
    content: "";
    position: absolute;
    top: 18px; right: 20px;
    width: 9px; height: 9px;
    background: #19E3B6;
    border-radius: 50%;
    box-shadow: 0 0 0 0 rgba(25,227,182, 0.7);
    animation: yc-dot 1.8s ease-in-out infinite;
    z-index: 2;
}
@keyframes yc-breathe {
    0%, 100% {
        border-color: rgba(25,227,182,0.30);
        box-shadow: 0 0 0 0 rgba(25,227,182, 0);
    }
    50% {
        border-color: rgba(25,227,182,0.65);
        box-shadow: 0 0 26px -4px rgba(25,227,182, 0.18);
    }
}
@keyframes yc-glow {
    0%, 100% { opacity: 0.55; transform: scale(0.92); }
    50%      { opacity: 1.0;  transform: scale(1.08); }
}
@keyframes yc-dot {
    0%   { box-shadow: 0 0 0 0 rgba(25,227,182, 0.75); transform: scale(1); }
    70%  { box-shadow: 0 0 0 12px rgba(25,227,182, 0); transform: scale(1.05); }
    100% { box-shadow: 0 0 0 0 rgba(25,227,182, 0); transform: scale(1); }
}

/* Section titles */
.sec {
    display: flex; align-items: baseline; justify-content: space-between;
    margin: 8px 0 12px 0;
}
.sec h3 { margin: 0; }
.sec .sec-sub { color: #71717A; font-size: 12px; }

/* Executive Brief card */
.brief-card {
    background: linear-gradient(160deg, #131318 0%, #0E0E13 100%);
    border: 1px solid #23232B;
    border-radius: 18px;
    padding: 28px 36px;
    margin-bottom: 18px;
    position: relative;
    overflow: hidden;
}
.brief-card::before {
    content: ""; position: absolute; left: 0; top: 0; bottom: 0;
    width: 3px; background: linear-gradient(180deg, #19E3B6, transparent 70%);
}
.brief-card p {
    color: #D4D4D8;
    font-size: 14.5px;
    line-height: 1.85;
    margin: 0 0 14px 0;
    font-weight: 400;
    letter-spacing: 0.005em;
}
.brief-card p:last-child { margin-bottom: 0; }
.brief-card p b {
    color: #F4F4F5;
    font-weight: 600;
}
.brief-card .brief-lead {
    font-size: 16.5px;
    line-height: 1.75;
    color: #E4E4E7;
    border-bottom: 1px solid #1F1F26;
    padding-bottom: 18px;
    margin-bottom: 18px;
}
.brief-card .brief-callout {
    margin-top: 18px;
    padding: 14px 18px;
    border-radius: 12px;
    font-size: 13.5px !important;
    line-height: 1.7 !important;
}
.brief-card .brief-good {
    background: rgba(34, 197, 94, 0.08);
    border: 1px solid rgba(34, 197, 94, 0.25);
    color: #BBF7D0 !important;
}
.brief-card .brief-neutral {
    background: rgba(245, 181, 68, 0.06);
    border: 1px solid rgba(245, 181, 68, 0.20);
    color: #FDE68A !important;
}
.brief-card .brief-bad {
    background: rgba(248, 113, 113, 0.06);
    border: 1px solid rgba(248, 113, 113, 0.25);
    color: #FECACA !important;
}

/* Insight chips */
.insights {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 10px; margin-bottom: 12px;
}
.insight {
    background: #111114; border: 1px solid #23232B;
    border-radius: 12px; padding: 12px 14px;
    display: flex; gap: 10px; align-items: flex-start;
}
.insight .ic {
    width: 28px; height: 28px; border-radius: 8px;
    background: rgba(25,227,182,0.08);
    color: #19E3B6; font-weight: 700;
    display: flex; align-items: center; justify-content: center;
    font-size: 14px; flex-shrink: 0;
}
.insight .tx { font-size: 12.5px; color: #D4D4D8; line-height: 1.5; }
.insight .tx b { color: #F4F4F5; }
</style>
"""


# =============================================================================
# CONFIG
# =============================================================================
st.set_page_config(
    page_title="Fyxx — Executive Insights",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

LIVE_TTL = 30          # today's slice TTL (seconds)
HISTORY_TTL = 900      # 15 min cache for multi-year backfill
REFRESH_SECONDS = 60   # in-place auto-refresh

# Same NET-of-VAT logic as the operational dashboard
VIRTUAL_CHANNELS_BY_CUSTOMER = {"Green Room": ["green room"]}
POS_CONFIG_CHANNEL_MAP = {
    3: "Green Room",
    2: "Retail",
    5: "Jasmine House",
    6: "Events (Mobile)",
}
EXCLUDED_POS_CONFIG_IDS = [4]


# =============================================================================
# CREDENTIALS
# =============================================================================
def _load_env_file(path):
    env = {}
    if not Path(path).exists():
        return env
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def get_creds():
    keys = ("ODOO_URL", "ODOO_DB", "ODOO_LOGIN", "ODOO_API_KEY")
    try:
        if all(k in st.secrets for k in keys):
            return {k: st.secrets[k] for k in keys} | {
                "DASHBOARD_PASSWORD": st.secrets.get("DASHBOARD_PASSWORD", "")
            }
    except Exception:
        pass

    env = _load_env_file(Path.home() / ".odoo-creds.env")
    if not all(k in env for k in keys):
        st.error("Could not find Odoo credentials.")
        st.stop()
    return {
        "ODOO_URL": env["ODOO_URL"],
        "ODOO_DB": env["ODOO_DB"],
        "ODOO_LOGIN": env["ODOO_LOGIN"],
        "ODOO_API_KEY": env["ODOO_API_KEY"],
        "DASHBOARD_PASSWORD": env.get("DASHBOARD_PASSWORD", ""),
    }


CREDS = get_creds()
URL = CREDS["ODOO_URL"].rstrip("/")
DB = CREDS["ODOO_DB"]
LOGIN = CREDS["ODOO_LOGIN"]
API_KEY = CREDS["ODOO_API_KEY"]
DASHBOARD_PASSWORD = CREDS["DASHBOARD_PASSWORD"]


# =============================================================================
# PASSWORD GATE
# =============================================================================
def check_password():
    if not DASHBOARD_PASSWORD:
        return True
    if st.session_state.get("auth_ok"):
        return True
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.markdown("<div style='height:60px'></div>", unsafe_allow_html=True)
        logo_uri = _logo_data_uri()
        if logo_uri:
            st.markdown(
                f"<div class='fyxx-logo' style='max-width:280px;margin:0 auto'>"
                f"<img src='{logo_uri}' /></div>",
                unsafe_allow_html=True,
            )
        st.markdown(
            "<p class='brand-tag' style='margin-top:18px'>Executive Insights</p>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p style='text-align:center;color:#A1A1AA;margin-bottom:24px;font-size:13px'>"
            "Enter the access password to continue.</p>",
            unsafe_allow_html=True,
        )
        pw = st.text_input("Password", type="password", key="pw_input",
                           label_visibility="collapsed", placeholder="Password")
        if st.button("Continue", use_container_width=True):
            if hmac.compare_digest(pw or "", DASHBOARD_PASSWORD):
                st.session_state["auth_ok"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    st.stop()


check_password()
st_autorefresh(interval=REFRESH_SECONDS * 1000, key="data-refresh")


# =============================================================================
# ODOO — READ-ONLY
# =============================================================================
@st.cache_resource(show_spinner=False)
def get_clients():
    common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common", allow_none=True)
    uid = common.authenticate(DB, LOGIN, API_KEY, {})
    if not uid:
        st.error("Odoo authentication failed.")
        st.stop()
    models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object", allow_none=True)
    return uid, models


def kw(model, method, args, opts=None):
    """Read-only wrapper. Allowed methods are read/search/search_read/search_count only."""
    if method not in {"read", "search", "search_read", "search_count"}:
        raise RuntimeError(f"Refused non-read method: {method}")
    uid, models = get_clients()
    return models.execute_kw(DB, uid, API_KEY, model, method, args, opts or {})


@st.cache_data(ttl=HISTORY_TTL, show_spinner=False)
def get_user_info():
    uid, _ = get_clients()
    user = kw("res.users", "read", [[uid]],
              {"fields": ["name", "company_id", "tz"]})[0]
    company = kw("res.company", "read", [[user["company_id"][0]]],
                 {"fields": ["name", "currency_id"]})[0]
    return {
        "user_name": user["name"],
        "company_name": company["name"],
        "currency": company["currency_id"][1] if company["currency_id"] else "",
        "tz": user.get("tz") or "UTC",
    }


def resolve_channel_so(team_name, customer_name):
    cust_lc = (customer_name or "").lower()
    for label, kws in VIRTUAL_CHANNELS_BY_CUSTOMER.items():
        if any(k in cust_lc for k in kws):
            return label
    return team_name or "No team"


# =============================================================================
# DATA FETCH (read-only) + CONSOLIDATION
# =============================================================================
def _to_local_dt(dt_str, tz):
    return (datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            .replace(tzinfo=timezone.utc)
            .astimezone(ZoneInfo(tz)))


def _date_window_utc(start_date, end_date, tz):
    start_local = datetime.combine(start_date, datetime.min.time(), ZoneInfo(tz))
    end_local = datetime.combine(end_date, datetime.min.time(), ZoneInfo(tz)) + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


@st.cache_data(ttl=HISTORY_TTL, show_spinner=False)
def fetch_orders_window(start_iso, end_iso, _ttl_bucket):
    """Fetch sale.order + pos.order in a UTC window. Returns flat row list."""
    so_domain = [
        ["date_order", ">=", start_iso],
        ["date_order", "<=", end_iso],
        ["state", "in", ["sale", "done"]],
    ]
    so_fields = ["name", "partner_id", "user_id", "team_id",
                 "amount_untaxed", "amount_tax", "currency_id",
                 "state", "date_order"]
    sos = kw("sale.order", "search_read", [so_domain],
             {"fields": so_fields, "limit": 200000, "order": "date_order asc"})

    pos_domain = [
        ["date_order", ">=", start_iso],
        ["date_order", "<=", end_iso],
        ["state", "in", ["paid", "done", "invoiced"]],
        ["config_id", "not in", EXCLUDED_POS_CONFIG_IDS],
    ]
    pos_fields = ["name", "partner_id", "user_id", "config_id",
                  "amount_total", "amount_tax", "state", "date_order"]
    try:
        poss = kw("pos.order", "search_read", [pos_domain],
                  {"fields": pos_fields, "limit": 200000, "order": "date_order asc"})
    except Exception:
        poss = []

    rows = []
    for o in sos:
        team_name = o["team_id"][1] if o.get("team_id") else None
        customer = o["partner_id"][1] if o.get("partner_id") else "—"
        salesperson = o["user_id"][1] if o.get("user_id") else "—"
        rows.append({
            "name": o["name"],
            "channel": resolve_channel_so(team_name, customer),
            "customer": customer,
            "salesperson": salesperson,
            "amount_total": o.get("amount_untaxed", 0.0),
            "date_order": o["date_order"],
            "state": o["state"],
            "source": "Sales Order",
        })
    for o in poss:
        cid = o["config_id"][0] if o.get("config_id") else None
        channel = POS_CONFIG_CHANNEL_MAP.get(
            cid, o["config_id"][1] if o.get("config_id") else "POS"
        )
        customer = o["partner_id"][1] if o.get("partner_id") else "Walk-in"
        salesperson = o["user_id"][1] if o.get("user_id") else "—"
        net = (o.get("amount_total") or 0) - (o.get("amount_tax") or 0)
        rows.append({
            "name": o["name"],
            "channel": channel,
            "customer": customer,
            "salesperson": salesperson,
            "amount_total": net,
            "date_order": o["date_order"],
            "state": o["state"],
            "source": "POS Ticket",
        })
    return rows


def load_dataframe(start_date, end_date, tz, ttl_bucket):
    start_utc, end_utc = _date_window_utc(start_date, end_date, tz)
    rows = fetch_orders_window(
        start_utc.strftime("%Y-%m-%d %H:%M:%S"),
        end_utc.strftime("%Y-%m-%d %H:%M:%S"),
        ttl_bucket,
    )
    if not rows:
        return pd.DataFrame(columns=[
            "name", "channel", "customer", "salesperson",
            "amount_total", "date_order", "state", "source",
            "dt_local", "year", "month", "day",
        ])
    df = pd.DataFrame(rows)
    df["dt_local"] = df["date_order"].apply(lambda s: _to_local_dt(s, tz))
    df["year"] = df["dt_local"].dt.year
    df["month"] = df["dt_local"].dt.month
    df["day"] = df["dt_local"].dt.date
    return df


# =============================================================================
# FORMAT HELPERS
# =============================================================================
def fmt_money(n, currency, compact=False):
    if n is None:
        return "—"
    if compact:
        if abs(n) >= 1_000_000:
            return f"{n/1_000_000:.2f}M {currency}"
        if abs(n) >= 1_000:
            return f"{n/1_000:.1f}K {currency}"
    return f"{n:,.0f} {currency}"


def delta_pct(a, b):
    if not b:
        return None
    return (a - b) / b * 100


def delta_html(curr, prev, label=""):
    pct = delta_pct(curr, prev)
    if pct is None:
        return f"<span style='color:#71717A'>no prior data</span>"
    if pct >= 0:
        return f"<span class='kpi-delta-up'>▲ {pct:.1f}%</span> <span style='color:#71717A'>{label}</span>"
    return f"<span class='kpi-delta-dn'>▼ {abs(pct):.1f}%</span> <span style='color:#71717A'>{label}</span>"


def style_fig(fig, height=320, show_legend=True):
    fig.update_layout(
        plot_bgcolor=PALETTE["surface"],
        paper_bgcolor=PALETTE["surface"],
        font=dict(family="Inter, -apple-system, sans-serif",
                  color=PALETTE["text_dim"], size=12),
        colorway=CHART_COLORWAY,
        margin=dict(l=8, r=8, t=10, b=8),
        height=height,
        showlegend=show_legend,
        legend=dict(
            orientation="h", yanchor="bottom", y=-0.22, xanchor="left", x=0,
            font=dict(size=11, color=PALETTE["text_dim"]),
            bgcolor="rgba(0,0,0,0)",
        ),
        hoverlabel=dict(bgcolor=PALETTE["surface2"],
                        bordercolor=PALETTE["border_lt"],
                        font_color=PALETTE["text"],
                        font_family="Inter"),
    )
    fig.update_xaxes(showgrid=False, showline=False, ticks="",
                     tickfont=dict(size=11, color=PALETTE["muted"]),
                     zerolinecolor=PALETTE["border"])
    fig.update_yaxes(gridcolor=PALETTE["border"], showline=False, ticks="",
                     tickfont=dict(size=11, color=PALETTE["muted"]),
                     zeroline=False)
    return fig


# =============================================================================
# SIDEBAR
# =============================================================================
info = get_user_info()
TZ = info["tz"]
CURRENCY = info["currency"]
today_local = datetime.now(ZoneInfo(TZ)).date()

with st.sidebar:
    logo_uri = _logo_data_uri()
    if logo_uri:
        st.markdown(
            f"<div class='fyxx-logo'><img src='{logo_uri}' /></div>",
            unsafe_allow_html=True,
        )
    st.markdown("<p class='brand-tag'>Executive Insights</p>", unsafe_allow_html=True)

    st.markdown("<h3>Years</h3>", unsafe_allow_html=True)
    current_year = today_local.year
    available_years = list(range(current_year - 2, current_year + 1))
    selected_years = st.multiselect(
        "Years", available_years, default=available_years,
        label_visibility="collapsed",
    )
    if not selected_years:
        selected_years = [current_year]

    history_start_year = min(selected_years)
    history_end_year = max(selected_years)

    st.markdown("---")
    if st.button("◌  Refresh now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption(
        f"<span style='color:#71717A;font-size:11px'>"
        f"Auto-refresh every {REFRESH_SECONDS}s · live + cached history"
        "</span>",
        unsafe_allow_html=True,
    )


# =============================================================================
# DATA LOAD
# =============================================================================
# Two cache tiers:
#   1) historical bulk (15-min TTL, bucketed by 15-min key)
#   2) today's live slice (30s TTL, bucketed by 30s key)
hist_bucket = int(datetime.now(timezone.utc).timestamp()) // HISTORY_TTL
live_bucket = int(datetime.now(timezone.utc).timestamp()) // LIVE_TTL

hist_start_date = date(history_start_year, 1, 1)
hist_end_date = date(history_end_year, 12, 31)
# Cap end at today to avoid pulling future empty range
if hist_end_date > today_local:
    hist_end_date = today_local

with st.spinner("Loading multi-year sales history..."):
    df_hist = load_dataframe(hist_start_date, hist_end_date, TZ, hist_bucket)

# Today live slice (in case history cache is older than today's tail)
today_live = load_dataframe(today_local, today_local, TZ, live_bucket)
if not today_live.empty:
    df_hist = df_hist[df_hist["day"] != today_local]
    df_hist = pd.concat([df_hist, today_live], ignore_index=True)

# Channel list (built from data)
all_channels = sorted(df_hist["channel"].dropna().unique().tolist()) if not df_hist.empty else []


# =============================================================================
# TICKER PLACEHOLDER — reserved at the very top, filled after data is computed
# =============================================================================
ticker_slot = st.empty()


# =============================================================================
# TOP SLICER BAR — period + channels live at the top of the report
# =============================================================================
st.markdown(
    "<div style='margin-top:-8px;margin-bottom:6px;color:#71717A;"
    "font-size:11px;font-weight:600;text-transform:uppercase;"
    "letter-spacing:0.18em'>Period</div>",
    unsafe_allow_html=True,
)
quick_options = ["Today", "Yesterday", "This Week", "This Month",
                 "YTD", "Last 7 Days", "Last 30 Days", "Last 12 Months",
                 "Full Year", "Custom"]
try:
    scope = st.pills(
        "Scope", quick_options, default="Today",
        selection_mode="single", label_visibility="collapsed",
        key="scope_pills_top",
    )
except Exception:
    try:
        scope = st.segmented_control(
            "Scope", quick_options, default="Today",
            label_visibility="collapsed", key="scope_seg_top",
        )
    except Exception:
        scope = st.radio(
            "Scope", quick_options, index=0,
            label_visibility="collapsed",
        )
if not scope:
    scope = "Today"

if scope == "Custom":
    cr_col1, cr_col2, _ = st.columns([1, 1, 3])
    with cr_col1:
        custom_start_picked = st.date_input(
            "From", value=date(current_year, 1, 1), key="custom_from",
        )
    with cr_col2:
        custom_end_picked = st.date_input(
            "To", value=today_local, key="custom_to",
        )
    custom_start, custom_end = custom_start_picked, custom_end_picked
else:
    custom_start = custom_end = None

st.markdown(
    "<div style='margin-top:14px;margin-bottom:6px;color:#71717A;"
    "font-size:11px;font-weight:600;text-transform:uppercase;"
    "letter-spacing:0.18em'>Channels</div>",
    unsafe_allow_html=True,
)
try:
    selected_channels = st.pills(
        "Channels", all_channels, default=all_channels,
        selection_mode="multi", label_visibility="collapsed",
        key="ch_pills_top",
    )
except Exception:
    selected_channels = st.multiselect(
        "Channels", all_channels, default=all_channels,
        label_visibility="collapsed", key="ch_pick_top",
    )

if not selected_channels:
    selected_channels = all_channels

st.markdown(
    "<div style='height:1px;background:#1F1F26;margin:18px 0 14px 0'></div>",
    unsafe_allow_html=True,
)

# Apply channel + year filters
df = df_hist[df_hist["channel"].isin(selected_channels)].copy()


# =============================================================================
# DERIVE PERIOD WINDOWS (current vs prior, by scope)
# =============================================================================
def scope_window(scope, today, sel_years, custom_start, custom_end):
    """Returns (curr_start, curr_end, prev_start, prev_end, label)."""
    main_year = max(sel_years) if sel_years else today.year
    if scope == "Today":
        y = today - timedelta(days=1)
        return today, today, y, y, "Today"
    if scope == "Yesterday":
        y = today - timedelta(days=1)
        d2 = y - timedelta(days=1)
        return y, y, d2, d2, "Yesterday"
    if scope == "This Week":
        cs = today - timedelta(days=today.weekday())
        elapsed = (today - cs).days
        ps = cs - timedelta(days=7)
        pe = ps + timedelta(days=elapsed)
        return cs, today, ps, pe, "This Week"
    if scope == "This Month":
        cs = today.replace(day=1)
        elapsed = (today - cs).days
        prev_last = cs - timedelta(days=1)
        ps = prev_last.replace(day=1)
        pe = ps + timedelta(days=elapsed)
        return cs, today, ps, pe, "This Month"
    if scope == "Last 7 Days":
        cs = today - timedelta(days=6)
        ps = cs - timedelta(days=7)
        pe = cs - timedelta(days=1)
        return cs, today, ps, pe, "Last 7 Days"
    if scope == "YTD":
        cs = date(main_year, 1, 1)
        ce = today if main_year == today.year else date(main_year, 12, 31)
        ps = date(main_year - 1, 1, 1)
        pe = ce.replace(year=main_year - 1)
        return cs, ce, ps, pe, f"YTD {main_year}"
    if scope == "Full Year":
        cs = date(main_year, 1, 1)
        ce = date(main_year, 12, 31)
        ps = date(main_year - 1, 1, 1)
        pe = date(main_year - 1, 12, 31)
        return cs, ce, ps, pe, f"FY {main_year}"
    if scope == "Last 30 Days":
        cs = today - timedelta(days=29)
        ce = today
        ps = cs - timedelta(days=30)
        pe = cs - timedelta(days=1)
        return cs, ce, ps, pe, "Last 30 Days"
    if scope == "Last 12 Months":
        cs = today - timedelta(days=365)
        ce = today
        ps = cs - timedelta(days=365)
        pe = cs - timedelta(days=1)
        return cs, ce, ps, pe, "Last 12 Months"
    cs = custom_start or today.replace(month=1, day=1)
    ce = custom_end or today
    span = (ce - cs).days
    pe = cs - timedelta(days=1)
    ps = pe - timedelta(days=span)
    return cs, ce, ps, pe, f"{cs.isoformat()} → {ce.isoformat()}"


curr_start, curr_end, prev_start, prev_end, scope_label = scope_window(
    scope, today_local, selected_years, custom_start, custom_end
)


def slice_df(d, start, end):
    if d.empty:
        return d
    return d[(d["day"] >= start) & (d["day"] <= end)]


df_curr = slice_df(df, curr_start, curr_end)
df_prev = slice_df(df, prev_start, prev_end)


# =============================================================================
# TICKER — fill the top placeholder with channel KPIs in scrolling marquee
# =============================================================================
def _delta_chip(curr_val, prev_val):
    if not prev_val:
        return "<span class='delta flat'>· NEW</span>"
    pct = (curr_val - prev_val) / prev_val * 100
    cls = "up" if pct >= 0 else "dn"
    arrow = "▲" if pct >= 0 else "▼"
    return f"<span class='delta {cls}'>{arrow} {abs(pct):.1f}%</span>"


def build_ticker(df_curr, df_prev, scope_label, currency):
    items = []

    # ---- Total revenue tile ----
    rev = float(df_curr["amount_total"].sum()) if not df_curr.empty else 0.0
    prev_rev_t = float(df_prev["amount_total"].sum()) if not df_prev.empty else 0.0
    items.append(
        f"<div class='ticker-item'>"
        f"<span class='label'>{scope_label} · Total</span>"
        f"<span class='value'>{fmt_money(rev, currency, compact=True)}</span>"
        f"{_delta_chip(rev, prev_rev_t)}"
        f"</div>"
    )

    # ---- Orders tile ----
    orders_n = len(df_curr)
    prev_orders_n = len(df_prev) if not df_prev.empty else 0
    items.append(
        f"<div class='ticker-item'>"
        f"<span class='label'>Orders</span>"
        f"<span class='value'>{orders_n:,}</span>"
        f"{_delta_chip(orders_n, prev_orders_n)}"
        f"</div>"
    )

    # ---- AOV tile ----
    aov = (rev / orders_n) if orders_n else 0
    prev_aov_v = (prev_rev_t / prev_orders_n) if prev_orders_n else 0
    items.append(
        f"<div class='ticker-item'>"
        f"<span class='label'>AOV</span>"
        f"<span class='value'>{fmt_money(aov, currency)}</span>"
        f"{_delta_chip(aov, prev_aov_v)}"
        f"</div>"
    )

    # ---- Customers tile ----
    cust_n = df_curr["customer"].nunique() if not df_curr.empty else 0
    prev_cust_n = df_prev["customer"].nunique() if not df_prev.empty else 0
    items.append(
        f"<div class='ticker-item'>"
        f"<span class='label'>Customers</span>"
        f"<span class='value'>{cust_n:,}</span>"
        f"{_delta_chip(cust_n, prev_cust_n)}"
        f"</div>"
    )

    # ---- One tile per channel, sorted by current revenue ----
    if not df_curr.empty:
        ch_curr_s = df_curr.groupby("channel")["amount_total"].sum().sort_values(ascending=False)
        ch_prev_s = (df_prev.groupby("channel")["amount_total"].sum()
                     if not df_prev.empty else pd.Series(dtype=float))
        for ch_name, ch_val in ch_curr_s.items():
            items.append(
                f"<div class='ticker-item'>"
                f"<span class='label'>{ch_name}</span>"
                f"<span class='value'>{fmt_money(ch_val, currency, compact=True)}</span>"
                f"{_delta_chip(ch_val, ch_prev_s.get(ch_name, 0))}"
                f"</div>"
            )

    # ---- Top customer tile ----
    if not df_curr.empty:
        cust_rev_s = df_curr.groupby("customer")["amount_total"].sum().sort_values(ascending=False)
        if len(cust_rev_s) > 0:
            items.append(
                f"<div class='ticker-item'>"
                f"<span class='label'>Top Customer</span>"
                f"<span class='value'>{cust_rev_s.index[0]} · "
                f"{fmt_money(cust_rev_s.iloc[0], currency, compact=True)}</span>"
                f"</div>"
            )

    # ---- Top salesperson tile ----
    if not df_curr.empty:
        sp_rev_s = df_curr.groupby("salesperson")["amount_total"].sum().sort_values(ascending=False)
        if len(sp_rev_s) > 0:
            items.append(
                f"<div class='ticker-item'>"
                f"<span class='label'>Top Sales</span>"
                f"<span class='value'>{sp_rev_s.index[0]} · "
                f"{fmt_money(sp_rev_s.iloc[0], currency, compact=True)}</span>"
                f"</div>"
            )

    # ---- Best day tile ----
    if not df_curr.empty:
        by_day_s = df_curr.groupby("day")["amount_total"].sum()
        if not by_day_s.empty and len(by_day_s) > 1:
            best_day_s = by_day_s.idxmax()
            items.append(
                f"<div class='ticker-item'>"
                f"<span class='label'>Best Day</span>"
                f"<span class='value'>{best_day_s.strftime('%d %b')} · "
                f"{fmt_money(by_day_s.max(), currency, compact=True)}</span>"
                f"</div>"
            )

    if not items:
        return ""

    track = "".join(items)
    return (
        "<div class='ticker-bar'>"
        "<div class='ticker-live'><span class='dot'></span>Live</div>"
        "<div class='ticker-mask'>"
        # Track is duplicated so the translateX -50% loop is seamless
        f"<div class='ticker-track'>{track}{track}</div>"
        "</div>"
        "</div>"
    )


ticker_slot.markdown(
    build_ticker(df_curr, df_prev, scope_label, CURRENCY),
    unsafe_allow_html=True,
)


# =============================================================================
# HERO HEADER
# =============================================================================
now_local = datetime.now(ZoneInfo(TZ))
hero_logo_html = (
    f"<div class='hero-logo'><img src='{logo_uri}' alt='Fyxx'/></div>"
    if logo_uri else ""
)
st.markdown(textwrap.dedent(f"""
<div class='hero'>
<div class='hero-left'>
{hero_logo_html}
<div>
<div class='hero-eyebrow'>{info['company_name']} · Executive Insights</div>
<h1><span class='hero-accent'>{scope_label}</span><span style='color:#52525B;font-weight:400'> · multi-year view</span></h1>
</div>
</div>
<div style='text-align:right'>
<span class='live-pill'><span class='live-dot'></span> Live</span>
<div style='color:#71717A;font-size:11.5px;margin-top:8px'>Updated {now_local.strftime("%H:%M:%S")} · {TZ}</div>
</div>
</div>
""").strip(), unsafe_allow_html=True)


# =============================================================================
# YEAR-PERFORMANCE CARDS  (mirrors the reference Power BI shot)
# =============================================================================
def year_card(year, df_year, df_prev_year, period_label, is_current=False):
    rev = float(df_year["amount_total"].sum()) if not df_year.empty else 0.0
    orders = len(df_year)
    customers = df_year["customer"].nunique() if not df_year.empty else 0
    aov = rev / orders if orders else 0
    prev_rev = float(df_prev_year["amount_total"].sum()) if not df_prev_year.empty else 0.0
    pct = delta_pct(rev, prev_rev)
    growth_html = ""
    if pct is not None:
        cls = "kpi-delta-up" if pct >= 0 else "kpi-delta-dn"
        arrow = "▲" if pct >= 0 else "▼"
        growth_html = (f"<div style='margin-top:14px'><span class='{cls}'>"
                       f"{arrow} {abs(pct):.1f}%</span> "
                       f"<span style='color:#71717A;font-size:12px'>vs {year-1}</span></div>")
    cls = "year-card is-current" if is_current else "year-card"
    return (
        f"<div class='{cls}'>"
        f"<div class='year-label'>{year} · {period_label}</div>"
        f"<div class='year-value'>{fmt_money(rev, CURRENCY, compact=True)}</div>"
        f"<div class='year-meta'>"
        f"Orders: <b style='color:#E4E4E7'>{orders:,}</b><br>"
        f"Avg order: <b style='color:#E4E4E7'>{fmt_money(aov, CURRENCY)}</b><br>"
        f"Customers: <b style='color:#E4E4E7'>{customers:,}</b>"
        f"</div>"
        f"{growth_html}"
        f"</div>"
    )


# Year cards now follow the active period slicer — for each selected year,
# the same calendar window as the current scope is shown (apples-to-apples).
def _shift_year(d, year):
    """Replace the year of a date, mapping Feb 29 -> Feb 28 for non-leap years."""
    try:
        return d.replace(year=year)
    except ValueError:
        return d.replace(year=year, day=28)


def year_window_for_scope(year, today, cs, ce):
    """Translate the current scope window (cs..ce) into the target year."""
    # If the scope window spans multiple years (e.g., Last 12 Months),
    # fall back to a calendar-year slice for that target year.
    if cs.year != ce.year:
        ws = date(year, 1, 1)
        we = date(year, 12, 31)
    else:
        ws = _shift_year(cs, year)
        we = _shift_year(ce, year)
    # Cap at today for the current calendar year (no future data).
    if year == today.year and we > today:
        we = today
    return ws, we


def year_card_slice(d, year, today, cs, ce):
    if d.empty:
        return d
    ws, we = year_window_for_scope(year, today, cs, ce)
    return d[(d["day"] >= ws) & (d["day"] <= we)]


# Build year cards but skip years that have no data in the active window
# (e.g. years before the business started or future years not yet realised).
years_for_cards = sorted(selected_years)
year_card_payload = []
for y in years_for_cards:
    d_y = year_card_slice(df, y, today_local, curr_start, curr_end)
    if d_y.empty:
        continue
    is_current = (y == today_local.year)
    d_prev = year_card_slice(df, y - 1, today_local, curr_start, curr_end)
    year_card_payload.append(year_card(y, d_y, d_prev, scope_label, is_current))

if year_card_payload:
    cards_html = (["<div class='kpi-grid' style='margin-bottom:6px'>"]
                  + year_card_payload + ["</div>"])
    st.markdown("\n".join(cards_html), unsafe_allow_html=True)
# Track which years actually contributed data, so multi-year charts only
# render lines that exist (no flat zero traces cluttering the legend).
years_with_data = [y for y in years_for_cards
                   if not df[df["year"] == y].empty]


# =============================================================================
# KPI ROW (current scope vs prior period)
# =============================================================================
curr_rev = float(df_curr["amount_total"].sum()) if not df_curr.empty else 0.0
prev_rev = float(df_prev["amount_total"].sum()) if not df_prev.empty else 0.0
curr_orders = len(df_curr)
prev_orders = len(df_prev)
curr_aov = curr_rev / curr_orders if curr_orders else 0
prev_aov = prev_rev / prev_orders if prev_orders else 0
curr_customers = df_curr["customer"].nunique() if not df_curr.empty else 0
prev_customers = df_prev["customer"].nunique() if not df_prev.empty else 0


def kpi_card(label, value, sub_html="", foot=""):
    foot_html = f"<div class='kpi-foot'>{foot}</div>" if foot else ""
    return (
        f"<div class='kpi'>"
        f"<div class='kpi-label'>{label}</div>"
        f"<div class='kpi-value'>{value}</div>"
        f"<div class='kpi-sub'>{sub_html}</div>"
        f"{foot_html}"
        f"</div>"
    )


kpi_html = "<div class='kpi-grid' style='margin-top:18px'>"
kpi_html += kpi_card(
    "Revenue (net of VAT)",
    fmt_money(curr_rev, CURRENCY, compact=True),
    delta_html(curr_rev, prev_rev, "vs prior period"),
    f"Prior: {fmt_money(prev_rev, CURRENCY, compact=True)}",
)
kpi_html += kpi_card(
    "Orders",
    f"{curr_orders:,}",
    delta_html(curr_orders, prev_orders, "vs prior period"),
    f"Prior: {prev_orders:,}",
)
kpi_html += kpi_card(
    "Avg order value",
    fmt_money(curr_aov, CURRENCY) if curr_orders else "—",
    delta_html(curr_aov, prev_aov, "vs prior period"),
    f"Prior: {fmt_money(prev_aov, CURRENCY)}" if prev_aov else "",
)
kpi_html += kpi_card(
    "Active customers",
    f"{curr_customers:,}",
    delta_html(curr_customers, prev_customers, "vs prior period"),
    f"Prior: {prev_customers:,}",
)
kpi_html += "</div>"
st.markdown(kpi_html, unsafe_allow_html=True)


# =============================================================================
# TABS
# =============================================================================
(tab_brief, tab_exec, tab_trends, tab_channels,
 tab_customers, tab_team, tab_recent) = st.tabs(
    ["  Brief  ", "  Executive Summary  ", "  Trends  ", "  Channels  ",
     "  Customers  ", "  Salespeople  ", "  Live Activity  "]
)


# -------- Written Brief --------
def _build_brief(df_curr, df_prev, scope_label, currency,
                 selected_channels, all_channels, today_local):
    """Generate a paragraph-style executive brief from the current slice."""
    if df_curr.empty:
        return ("<p class='brief-lead'>No transactions were recorded in the "
                f"<b>{scope_label}</b> window for the selected channels. "
                "Try widening the period or re-enabling channels in the slicer "
                "above.</p>")

    rev = float(df_curr["amount_total"].sum())
    prev = float(df_prev["amount_total"].sum()) if not df_prev.empty else 0.0
    pct = ((rev - prev) / prev * 100) if prev else None
    orders = len(df_curr)
    aov = rev / orders if orders else 0
    customers = df_curr["customer"].nunique()

    prev_orders = len(df_prev)
    prev_aov = (float(df_prev["amount_total"].sum()) / prev_orders) if prev_orders else 0
    prev_customers = df_prev["customer"].nunique() if not df_prev.empty else 0

    ch_rev = df_curr.groupby("channel")["amount_total"].sum().sort_values(ascending=False)
    cust_rev = df_curr.groupby("customer")["amount_total"].sum().sort_values(ascending=False)
    sp_rev = df_curr.groupby("salesperson")["amount_total"].sum().sort_values(ascending=False)
    by_day = df_curr.groupby("day")["amount_total"].sum().sort_values(ascending=False)

    # Channel YoY growth (current vs prior)
    ch_prev_rev = (df_prev.groupby("channel")["amount_total"].sum()
                   if not df_prev.empty else pd.Series(dtype=float))
    ch_growth = []
    for c, r in ch_rev.items():
        p = ch_prev_rev.get(c, 0)
        if p > 0:
            ch_growth.append((c, (r - p) / p * 100, r))
    ch_growth.sort(key=lambda x: x[1], reverse=True)

    def acc(v, color="#19E3B6"):
        return f"<b style='color:{color}'>{v}</b>"

    def signed_pct(p):
        if p is None:
            return "<span style='color:#71717A'>n/a</span>"
        sign = "+" if p >= 0 else "−"
        color = "#22C55E" if p >= 0 else "#F87171"
        return f"<b style='color:{color}'>{sign}{abs(p):.1f}%</b>"

    # Channel filter context
    ch_ctx = ""
    if all_channels and len(selected_channels) < len(all_channels):
        ch_ctx = (f" Filtered view: <b>{len(selected_channels)}</b> of "
                  f"{len(all_channels)} channels "
                  f"({', '.join(selected_channels)}).")

    # ----- Lead paragraph -----
    p_lead = (
        f"<p class='brief-lead'>"
        f"During <b>{scope_label}</b>, Fyxx generated "
        f"{acc(fmt_money(rev, currency, compact=True))} in net revenue "
        f"across {acc(f'{orders:,}')} transactions and "
        f"{acc(f'{customers:,}')} active customers. "
    )
    if pct is not None:
        direction = "ahead of" if pct >= 0 else "behind"
        p_lead += (f"That puts the period {signed_pct(pct)} {direction} "
                   f"the prior comparable window "
                   f"({fmt_money(prev, currency, compact=True)}). ")
    p_lead += f"Average order value sits at {acc(fmt_money(aov, currency))}"
    aov_pct = ((aov - prev_aov) / prev_aov * 100) if prev_aov else None
    if aov_pct is not None:
        p_lead += f", {signed_pct(aov_pct)} versus prior."
    else:
        p_lead += "."
    p_lead += ch_ctx + "</p>"

    # ----- Channel paragraph -----
    p_ch = ""
    if len(ch_rev) > 0:
        top_ch = ch_rev.index[0]
        top_ch_amt = ch_rev.iloc[0]
        top_ch_pct = top_ch_amt / rev * 100 if rev else 0
        p_ch = (
            f"<p><b>Channel mix.</b> "
            f"{acc(top_ch)} continues to lead, contributing "
            f"{acc(fmt_money(top_ch_amt, currency, compact=True))} "
            f"({top_ch_pct:.1f}% of revenue). "
        )
        if len(ch_rev) > 1:
            second = ch_rev.index[1]
            second_amt = ch_rev.iloc[1]
            second_pct = second_amt / rev * 100 if rev else 0
            p_ch += (f"{acc(second)} follows at "
                     f"{acc(fmt_money(second_amt, currency, compact=True))} "
                     f"({second_pct:.1f}%). ")
        if ch_growth:
            best_ch = ch_growth[0]
            worst_ch = ch_growth[-1]
            if best_ch[1] >= 0:
                p_ch += (f"Fastest-growing channel: {acc(best_ch[0])} "
                         f"at {signed_pct(best_ch[1])}. ")
            if worst_ch[1] < 0 and worst_ch[0] != best_ch[0]:
                p_ch += (f"Underperforming: {acc(worst_ch[0], '#F87171')} "
                         f"at {signed_pct(worst_ch[1])}. ")
        p_ch += "</p>"

    # ----- Customer + sales paragraph -----
    p_cust = "<p>"
    if len(cust_rev) > 0:
        top_cust = cust_rev.index[0]
        top_cust_amt = cust_rev.iloc[0]
        top_cust_pct = top_cust_amt / rev * 100 if rev else 0
        p_cust += (
            f"<b>Demand concentration.</b> "
            f"The single largest customer was {acc(top_cust)} at "
            f"{acc(fmt_money(top_cust_amt, currency, compact=True))} "
            f"({top_cust_pct:.1f}% of period revenue). "
        )
        # Top-10 share
        top10_share = cust_rev.head(10).sum() / rev * 100 if rev else 0
        p_cust += (f"The top 10 customers together account for "
                   f"{acc(f'{top10_share:.1f}%')} of revenue. ")
    if customers and prev_customers:
        cust_delta = (customers - prev_customers) / prev_customers * 100
        p_cust += (f"Active customer base moved {signed_pct(cust_delta)} "
                   f"versus the prior period.")
    p_cust += "</p>"

    # ----- Sales team paragraph -----
    p_team = ""
    if len(sp_rev) > 0:
        top_sp = sp_rev.index[0]
        top_sp_amt = sp_rev.iloc[0]
        top_sp_pct = top_sp_amt / rev * 100 if rev else 0
        p_team = (
            f"<p><b>Sales team.</b> "
            f"{acc(top_sp)} led the team, attributed with "
            f"{acc(fmt_money(top_sp_amt, currency, compact=True))} "
            f"({top_sp_pct:.1f}% of period revenue) "
        )
        if len(sp_rev) >= 3:
            top3_share = sp_rev.head(3).sum() / rev * 100 if rev else 0
            p_team += (f"and the top 3 salespeople drove "
                       f"{acc(f'{top3_share:.1f}%')} of total revenue.")
        else:
            p_team = p_team.rstrip() + "."
        p_team += "</p>"

    # ----- Standout day -----
    p_day = ""
    if not by_day.empty and len(by_day) > 1:
        best_day = by_day.idxmax()
        best_day_amt = by_day.max()
        avg_day = by_day.mean()
        ratio = best_day_amt / avg_day if avg_day else 1
        p_day = (
            f"<p><b>Standout day.</b> "
            f"{acc(best_day.strftime('%A · %d %b %Y'))} delivered "
            f"{acc(fmt_money(best_day_amt, currency, compact=True))}"
        )
        if ratio >= 1.5:
            p_day += f" — roughly {ratio:.1f}× the daily average for the period."
        else:
            p_day += "."
        p_day += "</p>"

    # ----- Direction / closing -----
    closing = ""
    if pct is not None:
        if pct >= 10:
            closing = (
                "<p class='brief-callout brief-good'>"
                "Net direction is clearly positive — momentum is on the upside. "
                "Recommended focus: protect the top-performing channel and "
                "double down on whatever drove the largest customers' purchases."
                "</p>"
            )
        elif pct >= 0:
            closing = (
                "<p class='brief-callout brief-neutral'>"
                "Performance is broadly in line with the prior period. "
                "Watch the underperforming channels and customer concentration "
                "as leading indicators."
                "</p>"
            )
        else:
            closing = (
                "<p class='brief-callout brief-bad'>"
                "Performance trails the prior period. "
                "Recommended focus: identify which channels and customers slipped, "
                "and whether the gap is volume (orders) or value (AOV) driven."
                "</p>"
            )

    return p_lead + p_ch + p_cust + p_team + p_day + closing


with tab_brief:
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='sec'><h3>Executive Brief</h3>"
        f"<div class='sec-sub'>Auto-generated narrative · {scope_label} "
        f"· {len(selected_channels)} channel(s)</div></div>",
        unsafe_allow_html=True,
    )
    brief_html = _build_brief(
        df_curr, df_prev, scope_label, CURRENCY,
        selected_channels, all_channels, today_local,
    )
    st.markdown(
        f"<div class='brief-card'>{brief_html}</div>",
        unsafe_allow_html=True,
    )
    # Quick top-3 table strip
    if not df_curr.empty:
        b1, b2, b3 = st.columns(3)
        with b1:
            st.markdown("<div class='sec'><h3>Top channels</h3></div>",
                        unsafe_allow_html=True)
            ch_top = (df_curr.groupby("channel")["amount_total"].sum()
                      .sort_values(ascending=False).head(5).reset_index())
            ch_top.columns = ["Channel", f"Revenue ({CURRENCY})"]
            st.dataframe(ch_top, use_container_width=True, hide_index=True,
                         column_config={f"Revenue ({CURRENCY})":
                                        st.column_config.NumberColumn(format="%,.0f")})
        with b2:
            st.markdown("<div class='sec'><h3>Top customers</h3></div>",
                        unsafe_allow_html=True)
            cu_top = (df_curr.groupby("customer")["amount_total"].sum()
                      .sort_values(ascending=False).head(5).reset_index())
            cu_top.columns = ["Customer", f"Revenue ({CURRENCY})"]
            st.dataframe(cu_top, use_container_width=True, hide_index=True,
                         column_config={f"Revenue ({CURRENCY})":
                                        st.column_config.NumberColumn(format="%,.0f")})
        with b3:
            st.markdown("<div class='sec'><h3>Top salespeople</h3></div>",
                        unsafe_allow_html=True)
            sp_top = (df_curr.groupby("salesperson")["amount_total"].sum()
                      .sort_values(ascending=False).head(5).reset_index())
            sp_top.columns = ["Salesperson", f"Revenue ({CURRENCY})"]
            st.dataframe(sp_top, use_container_width=True, hide_index=True,
                         column_config={f"Revenue ({CURRENCY})":
                                        st.column_config.NumberColumn(format="%,.0f")})


# -------- Executive Summary --------
with tab_exec:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # --- Insights chips: auto-generated takeaways ---
    insights_html = ["<div class='insights'>"]
    if not df_curr.empty:
        # Top channel
        ch_rev = (df_curr.groupby("channel")["amount_total"].sum()
                  .sort_values(ascending=False))
        if len(ch_rev) > 0:
            tch = ch_rev.index[0]
            tch_pct = ch_rev.iloc[0] / curr_rev * 100 if curr_rev else 0
            insights_html.append(
                f"<div class='insight'><div class='ic'>★</div>"
                f"<div class='tx'><b>{tch}</b> leads with <b>"
                f"{fmt_money(ch_rev.iloc[0], CURRENCY, compact=True)}</b> "
                f"({tch_pct:.1f}% of revenue).</div></div>"
            )
        # Growth flag
        if prev_rev:
            grw = (curr_rev - prev_rev) / prev_rev * 100
            arrow = "▲" if grw >= 0 else "▼"
            insights_html.append(
                f"<div class='insight'><div class='ic'>{arrow}</div>"
                f"<div class='tx'>Revenue is <b>{abs(grw):.1f}%</b> "
                f"{'higher' if grw >= 0 else 'lower'} than the prior comparable period.</div></div>"
            )
        # Best day
        by_day = df_curr.groupby("day")["amount_total"].sum()
        if not by_day.empty:
            best_day = by_day.idxmax()
            insights_html.append(
                f"<div class='insight'><div class='ic'>◆</div>"
                f"<div class='tx'>Best single day: <b>{best_day.strftime('%d %b %Y')}</b> "
                f"with <b>{fmt_money(by_day.max(), CURRENCY, compact=True)}</b>.</div></div>"
            )
        # Top customer
        cust_rev = df_curr.groupby("customer")["amount_total"].sum().sort_values(ascending=False)
        if not cust_rev.empty:
            tc = cust_rev.index[0]
            insights_html.append(
                f"<div class='insight'><div class='ic'>♦</div>"
                f"<div class='tx'>Top customer: <b>{tc}</b> — "
                f"<b>{fmt_money(cust_rev.iloc[0], CURRENCY, compact=True)}</b>.</div></div>"
            )
    insights_html.append("</div>")
    st.markdown("\n".join(insights_html), unsafe_allow_html=True)

    # --- Multi-year YTD line ---
    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("<div class='sec'><h3>Revenue trajectory · YTD by year</h3>"
                    "<div class='sec-sub'>Cumulative net revenue, day-of-year basis</div></div>",
                    unsafe_allow_html=True)
        if years_with_data:
            fig = go.Figure()
            for i, y in enumerate(years_with_data):
                d_y = df[df["year"] == y].copy()
                d_y["doy"] = d_y["dt_local"].dt.dayofyear
                daily = (d_y.groupby("doy")["amount_total"].sum()
                         .sort_index().cumsum())
                # Stop today's year at today's day-of-year
                if y == today_local.year:
                    cap_doy = today_local.timetuple().tm_yday
                    daily = daily[daily.index <= cap_doy]
                color = YEAR_COLORS[i % len(YEAR_COLORS)]
                if y == today_local.year:
                    color = PALETTE["neon"]
                # Label only the final point of each line so we don't crowd
                end_label = [""] * (len(daily) - 1) + [f"{daily.iloc[-1]:,.0f}"] if len(daily) else []
                fig.add_trace(go.Scatter(
                    x=daily.index, y=daily.values,
                    mode="lines+text",
                    name=str(y),
                    line=dict(width=2.6 if y == today_local.year else 2, color=color),
                    text=end_label,
                    textposition="top right",
                    textfont=dict(color=color, size=11),
                    cliponaxis=False,
                    hovertemplate=f"<b>{y}</b> · day %{{x}}<br>"
                                  f"%{{y:,.0f}} {CURRENCY}<extra></extra>",
                ))
            fig.update_xaxes(title=None,
                             tickvals=[1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335],
                             ticktext=["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
            fig.update_yaxes(title=None)
            st.plotly_chart(style_fig(fig, height=340), use_container_width=True)
        else:
            st.info("No data in selected window.")

    with c2:
        st.markdown("<div class='sec'><h3>Revenue mix by channel</h3>"
                    f"<div class='sec-sub'>{scope_label}</div></div>",
                    unsafe_allow_html=True)
        if not df_curr.empty:
            by_ch = (df_curr.groupby("channel")["amount_total"].sum()
                     .sort_values(ascending=False).reset_index())
            fig = go.Figure(data=[go.Pie(
                labels=by_ch["channel"], values=by_ch["amount_total"],
                hole=0.7,
                texttemplate="%{value:,.0f}<br>%{percent}",
                marker=dict(colors=CHART_COLORWAY,
                            line=dict(color=PALETTE["surface"], width=3)),
                hovertemplate="<b>%{label}</b><br>"
                              "%{value:,.0f} " + CURRENCY +
                              "<br>%{percent}<extra></extra>",
                textfont=dict(size=11, color=PALETTE["text"]),
            )])
            fig.update_layout(annotations=[dict(
                text=f"<b>{fmt_money(curr_rev, CURRENCY, compact=True)}</b>"
                     f"<br><span style='font-size:10px;color:#A1A1AA'>Total</span>",
                showarrow=False, font=dict(size=14, color=PALETTE["text"]))])
            st.plotly_chart(style_fig(fig, height=340), use_container_width=True)
        else:
            st.info("No data in selected window.")


# -------- Trends --------
with tab_trends:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    st.markdown("<div class='sec'><h3>Monthly revenue · year-over-year</h3>"
                "<div class='sec-sub'>Same calendar month, compared across years</div></div>",
                unsafe_allow_html=True)
    if years_with_data:
        fig = go.Figure()
        for i, y in enumerate(years_with_data):
            d_y = df[df["year"] == y]
            monthly = d_y.groupby("month")["amount_total"].sum().reindex(range(1, 13), fill_value=0)
            color = YEAR_COLORS[i % len(YEAR_COLORS)]
            if y == today_local.year:
                color = PALETTE["neon"]
            # Show data labels on non-zero months only
            label_text = [f"{v:,.0f}" if v else "" for v in monthly.values]
            fig.add_trace(go.Scatter(
                x=["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
                y=monthly.values, mode="lines+markers+text",
                name=str(y),
                line=dict(width=2.4, color=color, shape="spline", smoothing=0.6),
                marker=dict(size=6, color=color),
                text=label_text,
                textposition="top center",
                textfont=dict(color=color, size=10),
                cliponaxis=False,
                hovertemplate=f"<b>{y} · %{{x}}</b><br>"
                              f"%{{y:,.0f}} {CURRENCY}<extra></extra>",
            ))
        st.plotly_chart(style_fig(fig, height=380), use_container_width=True)
    else:
        st.info("No data in selected window.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"<div class='sec'><h3>Daily revenue · {scope_label}</h3>"
                    "<div class='sec-sub'>Net of VAT</div></div>",
                    unsafe_allow_html=True)
        if not df_curr.empty:
            daily = (df_curr.groupby("day")["amount_total"].sum()
                     .sort_index().reset_index())
            # Only attach text labels when there's room (≤ 45 days)
            show_labels = len(daily) <= 45
            fig = go.Figure(go.Bar(
                x=daily["day"], y=daily["amount_total"],
                text=daily["amount_total"] if show_labels else None,
                texttemplate="%{text:,.0f}" if show_labels else None,
                textposition="outside",
                textfont=dict(color=PALETTE["text_dim"], size=10),
                cliponaxis=False,
                marker=dict(color=PALETTE["neon"],
                            line=dict(width=0)),
                hovertemplate="<b>%{x|%d %b %Y}</b><br>"
                              "%{y:,.0f} " + CURRENCY + "<extra></extra>",
            ))
            st.plotly_chart(style_fig(fig, height=320, show_legend=False),
                            use_container_width=True)
        else:
            st.info("No data in selected window.")

    with c2:
        st.markdown("<div class='sec'><h3>Day-of-week × hour heatmap</h3>"
                    f"<div class='sec-sub'>{scope_label}</div></div>",
                    unsafe_allow_html=True)
        if not df_curr.empty:
            dh = df_curr.copy()
            dh["dow"] = dh["dt_local"].dt.day_name().str[:3]
            dh["hour"] = dh["dt_local"].dt.hour
            mat = (dh.groupby(["dow", "hour"])["amount_total"].sum()
                   .reset_index())
            order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            piv = mat.pivot(index="dow", columns="hour", values="amount_total").reindex(order)
            # Only label cells with non-zero values to keep it readable
            text_z = [[(f"{v:,.0f}" if v and v > 0 else "")
                       for v in row] for row in piv.values]
            fig = go.Figure(data=go.Heatmap(
                z=piv.values, x=piv.columns, y=piv.index,
                colorscale=[[0, "#0A0A0B"], [0.4, "#0E5A4A"],
                            [1, "#19E3B6"]],
                text=text_z,
                texttemplate="%{text}",
                textfont=dict(size=9, color="#0A0A0B"),
                hovertemplate="%{y} · %{x}:00<br>"
                              "%{z:,.0f} " + CURRENCY + "<extra></extra>",
                showscale=False,
            ))
            st.plotly_chart(style_fig(fig, height=320, show_legend=False),
                            use_container_width=True)
        else:
            st.info("No data in selected window.")


# -------- Channels --------
with tab_channels:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    st.markdown("<div class='sec'><h3>Channel performance · current vs prior</h3>"
                "<div class='sec-sub'>Side-by-side, net of VAT</div></div>",
                unsafe_allow_html=True)
    if not df_curr.empty:
        ch_curr = df_curr.groupby("channel")["amount_total"].sum()
        ch_prev = df_prev.groupby("channel")["amount_total"].sum() if not df_prev.empty else pd.Series(dtype=float)
        all_ch = sorted(set(list(ch_curr.index) + list(ch_prev.index)),
                        key=lambda x: -ch_curr.get(x, 0))
        prev_vals = [ch_prev.get(c, 0) for c in all_ch]
        curr_vals = [ch_curr.get(c, 0) for c in all_ch]
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=all_ch, y=prev_vals,
            name="Prior period",
            marker=dict(color=PALETTE["border_lt"], line=dict(width=0)),
            text=prev_vals, texttemplate="%{text:,.0f}",
            textposition="outside",
            textfont=dict(color=PALETTE["text_dim"], size=10),
            cliponaxis=False,
            hovertemplate="Prior · %{x}<br>%{y:,.0f} " + CURRENCY + "<extra></extra>",
        ))
        fig.add_trace(go.Bar(
            x=all_ch, y=curr_vals,
            name="Current",
            marker=dict(color=PALETTE["neon"], line=dict(width=0)),
            text=curr_vals, texttemplate="%{text:,.0f}",
            textposition="outside",
            textfont=dict(color=PALETTE["neon"], size=10),
            cliponaxis=False,
            hovertemplate="Current · %{x}<br>%{y:,.0f} " + CURRENCY + "<extra></extra>",
        ))
        fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.08)
        st.plotly_chart(style_fig(fig, height=380), use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='sec'><h3>Channel × year</h3></div>", unsafe_allow_html=True)
        if not df.empty:
            # Limit to years that actually have data
            cy_full = (df.groupby(["channel", "year"])["amount_total"].sum()
                       .reset_index())
            cy = cy_full[cy_full["year"].isin(years_with_data)]
            if not cy.empty:
                piv = cy.pivot(index="channel", columns="year",
                               values="amount_total").fillna(0)
                piv = piv.sort_values(piv.columns[-1], ascending=True)
                fig = go.Figure()
                for i, y in enumerate(piv.columns):
                    color = YEAR_COLORS[i % len(YEAR_COLORS)]
                    if y == today_local.year:
                        color = PALETTE["neon"]
                    fig.add_trace(go.Bar(
                        y=piv.index, x=piv[y], name=str(y), orientation="h",
                        marker=dict(color=color, line=dict(width=0)),
                        text=piv[y], texttemplate="%{text:,.0f}",
                        textposition="outside",
                        textfont=dict(color=color, size=10),
                        cliponaxis=False,
                        hovertemplate=f"<b>%{{y}}</b> · {y}<br>"
                                      f"%{{x:,.0f}} {CURRENCY}<extra></extra>",
                    ))
                fig.update_layout(barmode="group")
                st.plotly_chart(style_fig(fig, height=380), use_container_width=True)

    with c2:
        st.markdown("<div class='sec'><h3>Channel ranking</h3></div>", unsafe_allow_html=True)
        if not df_curr.empty:
            tbl = (df_curr.groupby("channel")
                   .agg(Revenue=("amount_total", "sum"),
                        Orders=("amount_total", "count"),
                        AOV=("amount_total", "mean"))
                   .sort_values("Revenue", ascending=False)
                   .reset_index())
            tbl.columns = ["Channel", f"Revenue ({CURRENCY})", "Orders", f"AOV ({CURRENCY})"]
            st.dataframe(
                tbl, use_container_width=True, hide_index=True,
                column_config={
                    f"Revenue ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                    f"AOV ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                    "Orders": st.column_config.NumberColumn(format="%,d"),
                },
            )


# -------- Customers --------
with tab_customers:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("<div class='sec'><h3>Top 20 customers</h3></div>", unsafe_allow_html=True)
        if not df_curr.empty:
            top = (df_curr.groupby("customer")["amount_total"].sum()
                   .sort_values(ascending=False).head(20).reset_index())
            top.columns = ["Customer", f"Revenue ({CURRENCY})"]
            st.dataframe(
                top, use_container_width=True, hide_index=True, height=520,
                column_config={f"Revenue ({CURRENCY})":
                               st.column_config.NumberColumn(format="%,.0f")},
            )
    with c2:
        st.markdown("<div class='sec'><h3>Customers by orders</h3></div>",
                    unsafe_allow_html=True)
        if not df_curr.empty:
            top = (df_curr.groupby("customer")
                   .agg(Orders=("amount_total", "count"),
                        Revenue=("amount_total", "sum"))
                   .sort_values("Orders", ascending=False).head(20).reset_index())
            top.columns = ["Customer", "Orders", f"Revenue ({CURRENCY})"]
            st.dataframe(
                top, use_container_width=True, hide_index=True, height=520,
                column_config={
                    f"Revenue ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                    "Orders": st.column_config.NumberColumn(format="%,d"),
                },
            )
    with c3:
        st.markdown("<div class='sec'><h3>Distribution</h3></div>", unsafe_allow_html=True)
        if not df_curr.empty:
            cust_rev = df_curr.groupby("customer")["amount_total"].sum().sort_values(ascending=False)
            total = cust_rev.sum()
            top10 = cust_rev.head(10).sum()
            top50 = cust_rev.head(50).sum()
            rest = total - top50
            cats = [
                ("Top 10", top10),
                ("Top 11–50", top50 - top10),
                ("Rest", rest),
            ]
            fig = go.Figure(data=[go.Pie(
                labels=[c[0] for c in cats], values=[c[1] for c in cats],
                hole=0.65,
                marker=dict(colors=[PALETTE["neon"], PALETTE["amber"],
                                    PALETTE["border_lt"]],
                            line=dict(color=PALETTE["surface"], width=3)),
                texttemplate="%{value:,.0f}<br>%{percent}",
                textfont=dict(size=11, color=PALETTE["text"]),
                hovertemplate="<b>%{label}</b><br>%{value:,.0f} " + CURRENCY +
                              "<br>%{percent}<extra></extra>",
            )])
            fig.update_layout(annotations=[dict(
                text=f"<b>{cust_rev.shape[0]:,}</b>"
                     f"<br><span style='font-size:10px;color:#A1A1AA'>Customers</span>",
                showarrow=False, font=dict(size=14, color=PALETTE["text"]))])
            st.plotly_chart(style_fig(fig, height=360), use_container_width=True)


# -------- Salespeople --------
with tab_team:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    st.markdown("<div class='sec'><h3>Salespeople leaderboard</h3>"
                f"<div class='sec-sub'>{scope_label}</div></div>",
                unsafe_allow_html=True)
    if not df_curr.empty:
        sp = (df_curr.groupby("salesperson")
              .agg(Revenue=("amount_total", "sum"),
                   Orders=("amount_total", "count"),
                   AOV=("amount_total", "mean"),
                   Customers=("customer", pd.Series.nunique))
              .sort_values("Revenue", ascending=False)
              .reset_index())
        sp.columns = ["Salesperson", f"Revenue ({CURRENCY})", "Orders",
                      f"AOV ({CURRENCY})", "Customers"]
        st.dataframe(
            sp, use_container_width=True, hide_index=True, height=520,
            column_config={
                f"Revenue ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                f"AOV ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                "Orders": st.column_config.NumberColumn(format="%,d"),
                "Customers": st.column_config.NumberColumn(format="%,d"),
            },
        )

    st.markdown("<div class='sec'><h3>Top 10 salespeople · revenue</h3></div>",
                unsafe_allow_html=True)
    if not df_curr.empty:
        top = (df_curr.groupby("salesperson")["amount_total"].sum()
               .sort_values(ascending=False).head(10))
        x_vals = top.values[::-1]
        y_vals = top.index[::-1]
        fig = go.Figure(go.Bar(
            x=x_vals, y=y_vals, orientation="h",
            marker=dict(
                color=x_vals,
                colorscale=[[0, "#0E5A4A"], [1, "#19E3B6"]],
                line=dict(width=0),
            ),
            text=x_vals,
            texttemplate="%{text:,.0f}",
            textposition="outside",
            textfont=dict(color=PALETTE["text_dim"], size=10),
            cliponaxis=False,
            hovertemplate="<b>%{y}</b><br>%{x:,.0f} " + CURRENCY + "<extra></extra>",
        ))
        st.plotly_chart(style_fig(fig, height=380, show_legend=False),
                        use_container_width=True)


# -------- Live Activity --------
with tab_recent:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    st.markdown("<div class='sec'><h3>Today's live ticker</h3>"
                f"<div class='sec-sub'>Auto-refreshes every {REFRESH_SECONDS}s</div></div>",
                unsafe_allow_html=True)
    today_df = df[df["day"] == today_local].copy()
    if today_df.empty:
        st.info("No activity yet today.")
    else:
        today_df = today_df.sort_values("dt_local", ascending=False)
        today_df["time"] = today_df["dt_local"].dt.strftime("%H:%M:%S")
        show = today_df[["time", "name", "channel", "source", "customer",
                         "salesperson", "amount_total", "state"]].copy()
        show.columns = ["Time", "Reference", "Channel", "Source", "Customer",
                        "Salesperson", f"Total ({CURRENCY})", "State"]
        st.dataframe(
            show.head(150), use_container_width=True, hide_index=True, height=560,
            column_config={f"Total ({CURRENCY})":
                           st.column_config.NumberColumn(format="%,.0f")},
        )


# =============================================================================
# FOOTER
# =============================================================================
st.markdown(
    f"<div style='text-align:center;color:#52525B;font-size:11px;"
    f"margin-top:36px;letter-spacing:0.04em'>"
    f"Fyxx Executive Insights · read-only · Odoo {DB} · "
    f"history cached {HISTORY_TTL//60} min · live tail {LIVE_TTL}s · "
    f"in-place refresh {REFRESH_SECONDS}s"
    f"</div>",
    unsafe_allow_html=True,
)
