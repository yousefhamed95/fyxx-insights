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
import uuid
import xmlrpc.client
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from threading import Lock
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

/* Page background — layered aurora glow, fixed so it doesn't scroll */
.stApp {
    background:
        radial-gradient(900px 520px at 12% -8%,  rgba(25, 227, 182, 0.10), transparent 65%),
        radial-gradient(820px 460px at 88%  4%,  rgba(56, 189, 248, 0.09), transparent 62%),
        radial-gradient(720px 500px at 50% 110%, rgba(167,139,250, 0.06), transparent 70%),
        #0A0A0B;
    background-attachment: fixed;
}
.block-container { padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1480px; }

/* Typography — refined editorial */
html, body, [class*="css"] {
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: #F4F4F5;
    /* tabular figures — digits all the same width so KPIs/tables don't jitter */
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum" 1, "lnum" 1;
}
h1, h2, h3, h4 {
    color: #F4F4F5;
    letter-spacing: -0.02em;
    font-weight: 700;
}
h1 { font-size: 30px !important; }
h2 { font-size: 18px !important; font-weight: 600 !important; color: #E4E4E7 !important; }
h3 { font-size: 13.5px !important; font-weight: 700 !important; color: #A1A1AA !important;
     text-transform: uppercase; letter-spacing: 0.10em; }

/* The hero scope label uses a teal→blue gradient (Linear-style) */
.hero-accent {
    color: #19E3B6;
    background: linear-gradient(90deg, #19E3B6 0%, #38BDF8 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

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
    box-shadow: 0 0 26px -10px rgba(56, 189, 248, 0.28),
                inset 0 0 0 1px rgba(56, 189, 248, 0.05);
}
.ticker-live {
    flex-shrink: 0;
    background: linear-gradient(90deg,
        rgba(56, 189, 248, 0.18) 0%,
        rgba(56, 189, 248, 0.04) 100%);
    border-right: 1px solid rgba(56, 189, 248, 0.32);
    display: flex; align-items: center; gap: 9px;
    padding: 0 18px;
    color: #38BDF8;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.20em;
    text-transform: uppercase;
    z-index: 2;
    text-shadow: 0 0 8px rgba(56, 189, 248, 0.45);
}
.ticker-live .dot {
    width: 7px; height: 7px;
    background: #38BDF8;
    border-radius: 50%;
    box-shadow: 0 0 8px #38BDF8;
    animation: ticker-pulse 1.8s infinite;
}
@keyframes ticker-pulse {
    0%   { box-shadow: 0 0 0 0 rgba(56, 189, 248, 0.75), 0 0 8px #38BDF8; }
    70%  { box-shadow: 0 0 0 9px rgba(56, 189, 248, 0), 0 0 8px #38BDF8; }
    100% { box-shadow: 0 0 0 0 rgba(56, 189, 248, 0), 0 0 8px #38BDF8; }
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
    animation: ticker-scroll 20s linear infinite;
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
    color: #38BDF8;
    font-weight: 700;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    font-size: 10.8px;
    opacity: 0.95;
    text-shadow: 0 0 6px rgba(56, 189, 248, 0.35);
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

/* Hero — animated gradient border using border-box trick (browser-safe) */
.hero {
    display: flex; align-items: center; justify-content: space-between;
    gap: 18px; flex-wrap: wrap;
    padding: 14px 18px;
    margin-bottom: 22px;
    border-radius: 14px;
    border: 1px solid transparent;
    background:
        linear-gradient(160deg, #131318 0%, #0E0E13 100%) padding-box,
        linear-gradient(135deg, #19E3B6, #38BDF8, #A78BFA, #38BDF8, #19E3B6) border-box;
    background-size: auto, 300% 300%;
    animation: hero-shimmer 12s linear infinite;
}
@keyframes hero-shimmer {
    0%   { background-position: 0% 0%, 0% 50%; }
    100% { background-position: 0% 0%, 300% 50%; }
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
.kpi-spark-row {
    margin-top: 10px;
    height: 30px;
    display: block;
    opacity: 0.92;
}
.kpi-spark { display: block; width: 100%; }

/* ===== Tier-1 polish: number-entry animation (bounce/overshoot for premium feel) ===== */
@keyframes value-fade-up {
    0%   { opacity: 0; transform: translateY(16px) scale(0.92); filter: blur(2px); }
    55%  { opacity: 1; transform: translateY(-3px) scale(1.025); filter: blur(0); }
    80%  { transform: translateY(1px) scale(0.998); }
    100% { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); }
}
.kpi-value, .year-value {
    animation: value-fade-up 0.85s cubic-bezier(0.34, 1.56, 0.64, 1) both;
    will-change: transform, opacity;
    display: inline-block;  /* needed so transforms apply cleanly */
}
/* Stagger so the four KPIs ripple in nicely instead of all at once */
.kpi-grid .kpi:nth-of-type(1) .kpi-value { animation-delay: 0.05s; }
.kpi-grid .kpi:nth-of-type(2) .kpi-value { animation-delay: 0.15s; }
.kpi-grid .kpi:nth-of-type(3) .kpi-value { animation-delay: 0.25s; }
.kpi-grid .kpi:nth-of-type(4) .kpi-value { animation-delay: 0.35s; }
.kpi-grid .kpi:nth-of-type(5) .kpi-value { animation-delay: 0.45s; }
.kpi-grid .year-card:nth-of-type(1) .year-value { animation-delay: 0.05s; }
.kpi-grid .year-card:nth-of-type(2) .year-value { animation-delay: 0.15s; }
.kpi-grid .year-card:nth-of-type(3) .year-value { animation-delay: 0.25s; }

/* ===== Tier-1 polish: editorial section numbering ===== */
[data-baseweb="tab-panel"] { counter-reset: section; }
[data-baseweb="tab-panel"] .sec h3 {
    counter-increment: section;
}
[data-baseweb="tab-panel"] .sec h3::before {
    content: counter(section, decimal-leading-zero) "  /  ";
    color: rgba(56, 189, 248, 0.55);
    font-weight: 500;
    font-style: normal;
    margin-right: 2px;
    letter-spacing: 0.10em;
    font-feature-settings: "tnum" 1;
}

/* ===== Tier-1 polish: hover micro-interactions ===== */
.kpi, .year-card, .alert-card, .insight, .brief-card {
    transition:
        transform 0.18s cubic-bezier(0.22, 0.61, 0.36, 1),
        box-shadow 0.22s ease,
        border-color 0.22s ease;
}
.kpi:hover {
    transform: translateY(-3px);
    box-shadow: 0 14px 36px -14px rgba(25, 227, 182, 0.32),
                0 1px 0 0 rgba(25, 227, 182, 0.12) inset;
    border-color: rgba(25, 227, 182, 0.32);
}
.year-card:hover {
    transform: translateY(-3px);
    box-shadow: 0 14px 36px -14px rgba(25, 227, 182, 0.34);
}
.alert-card:hover {
    transform: translateY(-1px);
    border-color: rgba(244, 244, 245, 0.20);
    box-shadow: 0 6px 22px -10px rgba(0, 0, 0, 0.4);
}
.insight:hover {
    border-color: rgba(25, 227, 182, 0.30);
    transform: translateY(-1px);
}
.brief-card:hover {
    border-color: rgba(56, 189, 248, 0.20);
    box-shadow: 0 8px 32px -16px rgba(56, 189, 248, 0.20);
}
/* Subtle shimmer-on-hover for KPI labels */
.kpi:hover .kpi-label {
    color: #19E3B6;
    transition: color 0.2s ease;
}

/* ===== Tier-1 polish: sticky scope strip ===== */
.scope-strip {
    position: sticky;
    top: 0;
    z-index: 50;
    margin: -8px 0 14px 0;
    padding: 8px 14px;
    border-radius: 10px;
    background: rgba(14, 14, 18, 0.78);
    -webkit-backdrop-filter: blur(10px);
            backdrop-filter: blur(10px);
    border: 1px solid #23232B;
    display: flex;
    align-items: center;
    gap: 14px;
    font-size: 11.5px;
    color: #A1A1AA;
    letter-spacing: 0.04em;
}
.scope-strip .pill {
    color: #19E3B6;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    font-size: 10.5px;
    padding: 2px 9px;
    border-radius: 999px;
    background: rgba(25, 227, 182, 0.10);
    border: 1px solid rgba(25, 227, 182, 0.25);
}
.scope-strip .dim { color: #71717A; }
.scope-strip b { color: #F4F4F5; font-weight: 600; }

/* ===== Live-viewer badge (top-left, fixed, glassmorphic) ===== */
.viewers-badge {
    position: fixed;
    top: 14px;
    left: 14px;
    z-index: 9999;
    background: rgba(14, 14, 18, 0.78);
    -webkit-backdrop-filter: blur(12px) saturate(1.2);
            backdrop-filter: blur(12px) saturate(1.2);
    border: 1px solid rgba(25, 227, 182, 0.28);
    border-radius: 999px;
    padding: 6px 14px 6px 10px;
    color: #A1A1AA;
    font-size: 11.5px;
    font-weight: 500;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    letter-spacing: 0.04em;
    box-shadow: 0 6px 22px -10px rgba(25, 227, 182, 0.30);
    pointer-events: none;
    user-select: none;
}
.viewers-badge .v-dot {
    width: 7px; height: 7px;
    border-radius: 50%;
    background: #19E3B6;
    box-shadow: 0 0 8px #19E3B6;
    animation: pulse 1.8s infinite;
    flex-shrink: 0;
}
.viewers-badge b {
    color: #F4F4F5;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
}
.viewers-badge .v-label {
    color: #71717A;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    font-size: 10px;
    font-weight: 600;
}
/* Hide on print */
@media print {
    .viewers-badge { display: none !important; }
}

/* ===== Print / PDF stylesheet ===== */
@media print {
    /* Hide everything that shouldn't appear in a printed report */
    section[data-testid="stSidebar"],
    [data-baseweb="tab-list"],
    .ticker-bar,
    .scope-strip,
    .stButton,
    [data-testid="stFileUploader"],
    button,
    iframe[title*="components"] {
        display: none !important;
    }
    /* Print-friendly: keep dark theme but remove animations and reduce shadows */
    .stApp {
        background: #0A0A0B !important;
    }
    .stApp::before, .stApp::after { display: none !important; }
    .kpi, .year-card, .alert-card, .brief-card, .hero,
    .insight, [data-testid="stDataFrame"], [data-testid="stMetric"] {
        animation: none !important;
        box-shadow: none !important;
        page-break-inside: avoid;
    }
    .kpi::after { display: none !important; }   /* moving beam */
    .year-card.is-current::before,
    .year-card.is-current::after { display: none !important; }
    .hero { background: #131318 !important; }
    /* Show ALL tab content sequentially when printing — gives a complete report */
    [data-baseweb="tab-panel"] {
        display: block !important;
        page-break-after: always;
    }
    .block-container {
        max-width: none !important;
        padding: 16px !important;
    }
    h1, h2, h3, h4 { page-break-after: avoid; }
}
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

/* Alerts grid */
.alert-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
    gap: 12px;
    margin-bottom: 8px;
}
.alert-card {
    background: linear-gradient(160deg, #131318 0%, #0E0E13 100%);
    border: 1px solid #23232B;
    border-radius: 12px;
    padding: 14px 18px;
    display: flex;
    gap: 12px;
    align-items: flex-start;
}
.alert-ic {
    width: 32px; height: 32px; border-radius: 9px;
    display: flex; align-items: center; justify-content: center;
    font-size: 14px; font-weight: 700;
    flex-shrink: 0;
}
.alert-body { flex: 1; min-width: 0; }
.alert-title {
    color: #F4F4F5;
    font-size: 13.5px;
    font-weight: 700;
    margin-bottom: 4px;
    letter-spacing: -0.005em;
}
.alert-tx {
    color: #A1A1AA;
    font-size: 12.5px;
    line-height: 1.6;
}
.alert-tx b { color: #F4F4F5; font-weight: 600; }

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

# Hard-coded Jordanian city coordinates (Odoo res.partner has city populated
# for ~92% of customers but partner_latitude/longitude are 0% populated).
JORDAN_CITIES = {
    "amman":        (31.9539, 35.9106),
    "irbid":        (32.5556, 35.8500),
    "zarqa":        (32.0728, 36.0876),
    "az zarqa":     (32.0728, 36.0876),
    "aqaba":        (29.5267, 35.0078),
    "al aqaba":     (29.5267, 35.0078),
    "madaba":       (31.7197, 35.7950),
    "salt":         (32.0392, 35.7272),
    "as salt":      (32.0392, 35.7272),
    "karak":        (31.1853, 35.7050),
    "al karak":     (31.1853, 35.7050),
    "mafraq":       (32.3500, 36.2080),
    "al mafraq":    (32.3500, 36.2080),
    "jerash":       (32.2811, 35.8997),
    "ajloun":       (32.3328, 35.7517),
    "ajlun":        (32.3328, 35.7517),
    "tafila":       (30.8369, 35.6044),
    "tafilah":      (30.8369, 35.6044),
    "at tafilah":   (30.8369, 35.6044),
    "maan":         (30.1962, 35.7239),
    "maan ":        (30.1962, 35.7239),
    "ma an":        (30.1962, 35.7239),
    "ramtha":       (32.5611, 36.0083),
    "fuheis":       (32.0050, 35.7758),
    "wadi musa":    (30.3214, 35.4794),
    "petra":        (30.3214, 35.4794),
    "sahab":        (31.8703, 36.0103),
    "naour":        (31.8786, 35.8275),
    "russeifa":     (32.0175, 36.0464),
    "ruseifa":      (32.0175, 36.0464),
    "rusayfa":      (32.0175, 36.0464),
    "abu nuseir":   (32.0589, 35.9536),
    "deir alla":    (32.2056, 35.6244),
    "shouneh":      (32.6133, 35.6058),
    "north shouneh":(32.6133, 35.6058),
    "south shouneh":(31.9181, 35.6125),
    "azraq":        (31.8333, 36.8167),
    "safi":         (31.0269, 35.4744),
    # Regional / international fallback cities
    "riyadh":       (24.7136, 46.6753),
    "dubai":        (25.2048, 55.2708),
    "abu dhabi":    (24.4539, 54.3773),
    "doha":         (25.2854, 51.5310),
    "kuwait":       (29.3759, 47.9774),
    "manama":       (26.2235, 50.5876),
    "muscat":       (23.5859, 58.4059),
    "beirut":       (33.8938, 35.5018),
    "damascus":     (33.5138, 36.2765),
    "cairo":        (30.0444, 31.2357),
    "jeddah":       (21.4858, 39.1925),
    "baghdad":      (33.3152, 44.3661),
    "ramallah":     (31.9038, 35.2034),
    "jerusalem":    (31.7683, 35.2137),
}


def _normalise_city(name):
    """Lower, trim, strip Arabic 'al-' prefix variants for fuzzy matching."""
    if not name:
        return None
    n = str(name).strip().lower()
    for prefix in ("al-", "al ", "el-", "el ", "ash-", "as-", "ash ", "as "):
        if n.startswith(prefix):
            n = n[len(prefix):]
    n = n.replace("'", "").replace("-", " ").replace("_", " ")
    n = " ".join(n.split())
    return n


def city_to_coords(city):
    """Return (lat, lon) for a city name, or None if unknown."""
    if not city:
        return None
    norm = _normalise_city(city)
    if norm in JORDAN_CITIES:
        return JORDAN_CITIES[norm]
    # Partial-match fallback (e.g. 'amman, jordan' contains 'amman')
    for key, coords in JORDAN_CITIES.items():
        if key and (key in norm or norm in key):
            return coords
    return None


# Channel mapping based on a deep audit of Fyxx Odoo (last-90-day data):
#   sale.order  → bucketed by warehouse_id (gives a meaningful split between
#                 e-commerce, B2B/Bonded, physical shop)
#   pos.order   → bucketed by config_id (Dine-In = Green Room, etc.)
#
# The previous "Sales" team bucket lumped 66% of revenue into one pill.
# Replacing with warehouse-based buckets exposes 4 distinct sub-channels.
WAREHOUSE_CHANNEL_MAP = {
    "Fyxx E-Commerce Warehouse": "Online",
    "Bonded Warehouse":          "B2B Bonded",
    "Fyxx Shop Warehouse":       "Fyxx Shop",
    "Fyxx Warehouse":            "Other Sales",
}
POS_CONFIG_CHANNEL_MAP = {
    3: "Green Room",        # Dine-In register
    2: "Retail",
    5: "Jasmine House",
    6: "Events (Mobile)",
}
EXCLUDED_POS_CONFIG_IDS = [4]   # Archived (testing POS)

# Stable colour per channel — keeps any chart visually consistent.
# Falls back to CHART_COLORWAY for channels not listed here.
CHANNEL_COLORS = {
    "Online":           "#19E3B6",  # primary neon (largest channel)
    "Green Room":       "#A78BFA",  # violet (hospitality)
    "B2B Bonded":       "#F5B544",  # amber/gold (premium / high-AOV)
    "Retail":           "#38BDF8",  # sky blue
    "Fyxx Shop":        "#EC4899",  # rose
    "Events (Mobile)":  "#22C55E",  # green
    "Jasmine House":    "#FBBF24",  # warm yellow
    "Other Sales":      "#71717A",  # muted grey
}


def channel_colors_for(channels):
    """Return a list of hex colours aligned to a list of channel names."""
    out = []
    fallback = list(CHART_COLORWAY)
    fb_i = 0
    for c in channels:
        if c in CHANNEL_COLORS:
            out.append(CHANNEL_COLORS[c])
        else:
            out.append(fallback[fb_i % len(fallback)])
            fb_i += 1
    return out


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
# LIVE VIEWER PRESENCE — counts active sessions on this worker
# =============================================================================
PRESENCE_TTL_SECONDS = 90  # a session that hasn't pinged in 90s is "gone"


@st.cache_resource(show_spinner=False)
def _presence_store():
    """Single dict shared across all Streamlit sessions running on this worker."""
    return {"sessions": {}, "lock": Lock()}


def update_presence():
    """Heartbeat the current session and return the live viewer count."""
    if "presence_id" not in st.session_state:
        st.session_state.presence_id = uuid.uuid4().hex[:12]
    store = _presence_store()
    now_ts = datetime.now(timezone.utc).timestamp()
    with store["lock"]:
        store["sessions"][st.session_state.presence_id] = now_ts
        cutoff = now_ts - PRESENCE_TTL_SECONDS
        store["sessions"] = {
            sid: ts for sid, ts in store["sessions"].items() if ts > cutoff
        }
        return len(store["sessions"])


_LIVE_VIEWERS = update_presence()


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


def resolve_channel_so(warehouse_name, team_name):
    """Map a sale.order to a friendly channel label.
    Primary signal is warehouse_id (e.g. 'Fyxx E-Commerce Warehouse' -> 'Online');
    falls back to team_id if no warehouse mapping is found."""
    if warehouse_name and warehouse_name in WAREHOUSE_CHANNEL_MAP:
        return WAREHOUSE_CHANNEL_MAP[warehouse_name]
    return team_name or "Other Sales"


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
    so_fields = ["name", "partner_id", "user_id", "team_id", "warehouse_id",
                 "amount_untaxed", "amount_tax", "currency_id",
                 "state", "date_order", "margin"]
    sos = kw("sale.order", "search_read", [so_domain],
             {"fields": so_fields, "limit": 200000, "order": "date_order asc"})

    pos_domain = [
        ["date_order", ">=", start_iso],
        ["date_order", "<=", end_iso],
        ["state", "in", ["paid", "done", "invoiced"]],
        ["config_id", "not in", EXCLUDED_POS_CONFIG_IDS],
    ]
    pos_fields = ["name", "partner_id", "user_id", "config_id",
                  "amount_total", "amount_tax", "state", "date_order", "margin"]
    try:
        poss = kw("pos.order", "search_read", [pos_domain],
                  {"fields": pos_fields, "limit": 200000, "order": "date_order asc"})
    except Exception:
        poss = []

    rows = []
    for o in sos:
        team_name = o["team_id"][1] if o.get("team_id") else None
        warehouse_name = o["warehouse_id"][1] if o.get("warehouse_id") else None
        partner_id = o["partner_id"][0] if o.get("partner_id") else None
        customer = o["partner_id"][1] if o.get("partner_id") else "—"
        salesperson = o["user_id"][1] if o.get("user_id") else "—"
        rows.append({
            "name": o["name"],
            "channel": resolve_channel_so(warehouse_name, team_name),
            "customer": customer,
            "partner_id": partner_id,
            "salesperson": salesperson,
            "amount_total": o.get("amount_untaxed", 0.0),
            "margin": float(o.get("margin") or 0),
            "date_order": o["date_order"],
            "state": o["state"],
            "source": "Sales Order",
        })
    for o in poss:
        cid = o["config_id"][0] if o.get("config_id") else None
        channel = POS_CONFIG_CHANNEL_MAP.get(
            cid, o["config_id"][1] if o.get("config_id") else "POS"
        )
        partner_id = o["partner_id"][0] if o.get("partner_id") else None
        customer = o["partner_id"][1] if o.get("partner_id") else "Walk-in"
        salesperson = o["user_id"][1] if o.get("user_id") else "—"
        net = (o.get("amount_total") or 0) - (o.get("amount_tax") or 0)
        rows.append({
            "name": o["name"],
            "channel": channel,
            "customer": customer,
            "partner_id": partner_id,
            "salesperson": salesperson,
            "amount_total": net,
            "margin": float(o.get("margin") or 0),
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
            "name", "channel", "customer", "partner_id", "salesperson",
            "amount_total", "margin", "date_order", "state", "source",
            "dt_local", "year", "month", "day",
        ])
    df = pd.DataFrame(rows)
    df["dt_local"] = df["date_order"].apply(lambda s: _to_local_dt(s, tz))
    df["year"] = df["dt_local"].dt.year
    df["month"] = df["dt_local"].dt.month
    df["day"] = df["dt_local"].dt.date
    return df


# Order-line fetcher (for the SKU / Products tab) — read-only, cached.
@st.cache_data(ttl=HISTORY_TTL, show_spinner=False)
def fetch_order_lines_window(start_iso, end_iso, _ttl_bucket):
    """Fetch sale.order.line + pos.order.line in a UTC window.
    Returns flat row list with product, qty, revenue (net), margin, channel hint."""
    so_lines = []
    pos_lines = []
    try:
        so_lines = kw(
            "sale.order.line", "search_read",
            [[["order_id.date_order", ">=", start_iso],
              ["order_id.date_order", "<=", end_iso],
              ["order_id.state", "in", ["sale", "done"]]]],
            {"fields": ["product_id", "product_uom_qty", "price_subtotal",
                        "margin", "purchase_price", "order_id"],
             "limit": 500000},
        )
    except Exception:
        so_lines = []
    try:
        pos_lines = kw(
            "pos.order.line", "search_read",
            [[["order_id.date_order", ">=", start_iso],
              ["order_id.date_order", "<=", end_iso],
              ["order_id.state", "in", ["paid", "done", "invoiced"]],
              ["order_id.config_id", "not in", EXCLUDED_POS_CONFIG_IDS]]],
            {"fields": ["product_id", "qty", "price_subtotal", "margin",
                        "total_cost", "order_id"],
             "limit": 500000},
        )
    except Exception:
        pos_lines = []

    rows = []
    for l in so_lines:
        if not l.get("product_id"):
            continue
        rows.append({
            "product_id": l["product_id"][0],
            "product_name": l["product_id"][1],
            "order_id": l["order_id"][0] if l.get("order_id") else None,
            "qty": float(l.get("product_uom_qty") or 0),
            "revenue": float(l.get("price_subtotal") or 0),
            "margin": float(l.get("margin") or 0),
            "source": "Sales Order",
        })
    for l in pos_lines:
        if not l.get("product_id"):
            continue
        rows.append({
            "product_id": l["product_id"][0],
            "product_name": l["product_id"][1],
            "order_id": l["order_id"][0] if l.get("order_id") else None,
            "qty": float(l.get("qty") or 0),
            "revenue": float(l.get("price_subtotal") or 0),
            "margin": float(l.get("margin") or 0),
            "source": "POS Ticket",
        })
    return rows


# Partner address lookup — read-only, cached 1 hour. Returns dict id -> info.
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_partner_addresses(partner_ids_tuple):
    """Read city/country/state for each partner ID (read-only)."""
    if not partner_ids_tuple:
        return {}
    ids = [int(i) for i in partner_ids_tuple if i]
    if not ids:
        return {}
    try:
        rows = kw("res.partner", "read", [ids],
                  {"fields": ["id", "name", "city", "country_id", "state_id",
                              "partner_latitude", "partner_longitude"]})
    except Exception:
        return {}
    out = {}
    for r in rows:
        out[r["id"]] = {
            "city": r.get("city") or None,
            "country": r["country_id"][1] if r.get("country_id") else None,
            "state": r["state_id"][1] if r.get("state_id") else None,
            "lat": r.get("partner_latitude") or None,
            "lon": r.get("partner_longitude") or None,
        }
    return out


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
                  color=PALETTE["text_dim"], size=11.5),
        colorway=CHART_COLORWAY,
        margin=dict(l=8, r=12, t=10, b=8),
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
                        font_family="Inter",
                        font_size=12),
    )
    fig.update_xaxes(
        showgrid=False, showline=False, ticks="",
        tickfont=dict(size=10.5, color=PALETTE["muted"]),
        zerolinecolor=PALETTE["border"],
    )
    fig.update_yaxes(
        gridcolor="rgba(255,255,255,0.045)",
        griddash="dot",
        gridwidth=1,
        showline=False,
        ticks="",
        tickfont=dict(size=10.5, color=PALETTE["muted"]),
        zeroline=False,
    )
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
    if st.button("⎙  Save as PDF", use_container_width=True,
                 help="Open the browser's print dialog — choose 'Save as PDF' "
                      "to export the current view as a branded report"):
        # Streamlit components run in an iframe, but we can call parent.print()
        from streamlit.components.v1 import html as _stcomp_html
        _stcomp_html(
            "<script>setTimeout(function(){"
            "try { window.parent.print(); } catch(e) { window.print(); }"
            "}, 200);</script>",
            height=0,
        )
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
# LIVE-VIEWER BADGE (fixed, top-left)
# =============================================================================
_viewer_word = "viewer" if _LIVE_VIEWERS == 1 else "viewers"
st.markdown(
    f"<div class='viewers-badge'>"
    f"<span class='v-dot'></span>"
    f"<b>{_LIVE_VIEWERS}</b>"
    f"<span class='v-label'>live {_viewer_word}</span>"
    f"</div>",
    unsafe_allow_html=True,
)


# =============================================================================
# STICKY SCOPE STRIP — stays visible while you scroll
# =============================================================================
_now_for_strip = datetime.now(ZoneInfo(TZ))
if all_channels and len(selected_channels) < len(all_channels):
    _strip_chans = f"{len(selected_channels)} of {len(all_channels)} channels"
elif all_channels:
    _strip_chans = f"all {len(all_channels)} channels"
else:
    _strip_chans = "no channels"
_scope_strip_html = (
    "<div class='scope-strip'>"
    f"<span class='pill'>{scope_label}</span>"
    f"<span class='dim'>·</span>"
    f"<span><b>{_strip_chans}</b></span>"
    f"<span class='dim'>·</span>"
    f"<span class='dim'>Updated {_now_for_strip.strftime('%H:%M:%S')} · {TZ}</span>"
    "</div>"
)
st.markdown(_scope_strip_html, unsafe_allow_html=True)


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


_SPARK_COUNTER = [0]


def sparkline_svg(values, width=200, height=30, color="#19E3B6"):
    """Inline SVG sparkline. Returns empty string if too few points."""
    try:
        vals = [float(v) for v in values if v is not None]
    except Exception:
        return ""
    if len(vals) < 2:
        return ""
    vmin, vmax = min(vals), max(vals)
    span = (vmax - vmin) if vmax > vmin else max(abs(vmax), 1.0)
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = (i / (n - 1)) * (width - 4) + 2
        y = height - ((v - vmin) / span) * (height - 8) - 4
        pts.append((x, y))
    line_d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    fill_pts = f"M{pts[0][0]:.1f},{pts[0][1]:.1f} " + " ".join(
        f"L{x:.1f},{y:.1f}" for x, y in pts[1:]
    ) + f" L{pts[-1][0]:.1f},{height-1:.1f} L{pts[0][0]:.1f},{height-1:.1f} Z"
    _SPARK_COUNTER[0] += 1
    fill_id = f"sk{_SPARK_COUNTER[0]}"
    last_x, last_y = pts[-1]
    return (
        f"<svg class='kpi-spark' viewBox='0 0 {width} {height}' "
        f"preserveAspectRatio='none'>"
        f"<defs><linearGradient id='{fill_id}' x1='0' x2='0' y1='0' y2='1'>"
        f"<stop offset='0%' stop-color='{color}' stop-opacity='0.30'/>"
        f"<stop offset='100%' stop-color='{color}' stop-opacity='0'/>"
        f"</linearGradient></defs>"
        f"<path d='{fill_pts}' fill='url(#{fill_id})'/>"
        f"<path d='{line_d}' stroke='{color}' stroke-width='1.6' fill='none' "
        f"stroke-linecap='round' stroke-linejoin='round'/>"
        f"<circle cx='{last_x:.1f}' cy='{last_y:.1f}' r='2.2' fill='{color}'/>"
        f"</svg>"
    )


def kpi_card(label, value, sub_html="", foot="", spark=None, spark_color="#19E3B6"):
    foot_html = f"<div class='kpi-foot'>{foot}</div>" if foot else ""
    spark_html = ""
    if spark:
        svg = sparkline_svg(spark, color=spark_color)
        if svg:
            spark_html = f"<div class='kpi-spark-row'>{svg}</div>"
    return (
        f"<div class='kpi'>"
        f"<div class='kpi-label'>{label}</div>"
        f"<div class='kpi-value'>{value}</div>"
        f"<div class='kpi-sub'>{sub_html}</div>"
        f"{spark_html}"
        f"{foot_html}"
        f"</div>"
    )


# Daily sparklines for the 4 main KPIs (only when the period spans 2+ days)
_spark_rev = _spark_orders = _spark_aov = _spark_cust = None
try:
    if not df_curr.empty and df_curr["day"].nunique() > 1:
        _daily_kpi = (df_curr.groupby("day")
                      .agg(rev=("amount_total", "sum"),
                           orders=("amount_total", "count"),
                           cust=("customer", pd.Series.nunique))
                      .sort_index()
                      .reset_index())
        _daily_kpi["aov"] = _daily_kpi.apply(
            lambda r: r["rev"] / r["orders"] if r["orders"] else 0, axis=1
        )
        _spark_rev = _daily_kpi["rev"].tolist()
        _spark_orders = _daily_kpi["orders"].tolist()
        _spark_aov = _daily_kpi["aov"].tolist()
        _spark_cust = _daily_kpi["cust"].tolist()
except Exception:
    pass

kpi_html = "<div class='kpi-grid' style='margin-top:18px'>"
kpi_html += kpi_card(
    "Revenue (net of VAT)",
    fmt_money(curr_rev, CURRENCY, compact=True),
    delta_html(curr_rev, prev_rev, "vs prior period"),
    f"Prior: {fmt_money(prev_rev, CURRENCY, compact=True)}",
    spark=_spark_rev, spark_color="#19E3B6",
)
kpi_html += kpi_card(
    "Orders",
    f"{curr_orders:,}",
    delta_html(curr_orders, prev_orders, "vs prior period"),
    f"Prior: {prev_orders:,}",
    spark=_spark_orders, spark_color="#38BDF8",
)
kpi_html += kpi_card(
    "Avg order value",
    fmt_money(curr_aov, CURRENCY) if curr_orders else "—",
    delta_html(curr_aov, prev_aov, "vs prior period"),
    f"Prior: {fmt_money(prev_aov, CURRENCY)}" if prev_aov else "",
    spark=_spark_aov, spark_color="#A78BFA",
)
kpi_html += kpi_card(
    "Active customers",
    f"{curr_customers:,}",
    delta_html(curr_customers, prev_customers, "vs prior period"),
    f"Prior: {prev_customers:,}",
    spark=_spark_cust, spark_color="#F5B544",
)
kpi_html += "</div>"
st.markdown(kpi_html, unsafe_allow_html=True)


# =============================================================================
# TABS
# =============================================================================
(tab_brief, tab_exec, tab_pace, tab_profit, tab_sku, tab_loss, tab_alerts,
 tab_trends, tab_channels, tab_customers, tab_cohorts, tab_team, tab_geo,
 tab_compare, tab_recent) = st.tabs(
    ["  ◆  Brief  ", "  ❖  Executive Summary  ", "  ▲  Pacing  ",
     "  ◯  Profitability  ", "  ❒  Products  ", "  ※  Loss Orders  ",
     "  ⚑  Alerts  ", "  ⌁  Trends  ", "  ⌬  Channels  ", "  ◐  Customers  ",
     "  ⟳  Cohorts  ", "  ★  Salespeople  ", "  ◉  Geography  ",
     "  ⇋  Compare  ", "  ●  Live  "]
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

    # ----- Profitability paragraph -----
    p_profit = ""
    if "margin" in df_curr.columns:
        profit_n = float(df_curr["margin"].sum())
        prev_profit_n = (float(df_prev["margin"].sum())
                         if not df_prev.empty and "margin" in df_prev.columns else 0)
        gm_pct = (profit_n / rev * 100) if rev else 0
        prev_gm_pct = (prev_profit_n / prev * 100) if prev else 0
        ch_prof = (df_curr.groupby("channel")
                   .agg(rev=("amount_total", "sum"),
                        prof=("margin", "sum"))
                   .reset_index())
        ch_prof["gm"] = ch_prof.apply(
            lambda r: r["prof"] / r["rev"] * 100 if r["rev"] else 0, axis=1
        )
        best_m = ch_prof.sort_values("gm", ascending=False).iloc[0] if not ch_prof.empty else None
        worst_m = ch_prof.sort_values("gm", ascending=True).iloc[0] if len(ch_prof) > 1 else None

        p_profit = (
            f"<p><b>Profitability.</b> "
            f"Gross profit was {acc(fmt_money(profit_n, currency, compact=True))} "
            f"on a margin of {acc(f'{gm_pct:.1f}%')}. "
        )
        if prev and prev_profit_n:
            ppt = gm_pct - prev_gm_pct
            color = "#22C55E" if ppt >= 0 else "#F87171"
            profit_pct_change = ((profit_n - prev_profit_n) / prev_profit_n * 100) if prev_profit_n else 0
            p_profit += (
                f"That's <span style='color:{color};font-weight:600'>"
                f"{ppt:+.1f}ppt</span> versus the prior period "
                f"(profit {signed_pct(profit_pct_change)}). "
            )
        if best_m is not None:
            best_gm = float(best_m["gm"])
            best_prof = float(best_m["prof"])
            p_profit += (
                f"Strongest margin: {acc(best_m['channel'])} at "
                f"{acc(f'{best_gm:.1f}%')} "
                f"delivering {acc(fmt_money(best_prof, currency, compact=True))} of profit. "
            )
        if (worst_m is not None and best_m is not None
                and worst_m["channel"] != best_m["channel"]):
            worst_gm = float(worst_m["gm"])
            p_profit += (
                f"Weakest: {acc(worst_m['channel'], '#F87171')} at "
                f"{acc(f'{worst_gm:.1f}%')}."
            )
        p_profit += "</p>"

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

    return p_lead + p_ch + p_profit + p_cust + p_team + p_day + closing


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
                marker=dict(colors=channel_colors_for(by_ch["channel"]),
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


# -------- Pacing & Forecast --------
with tab_pace:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # Determine the "active period" for pacing — the natural period container
    # for the current scope. Most useful for short scopes (Today, Week, Month, YTD).
    if scope == "Today":
        pace_start, pace_end = today_local, today_local
        pace_label = "Today"
        # For today we project hourly run-rate to end of day
        elapsed_secs = (now_local - now_local.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds()
        total_secs = 24 * 3600
        pct_elapsed = min(1.0, elapsed_secs / total_secs)
    elif scope == "This Week":
        pace_start = today_local - timedelta(days=today_local.weekday())
        pace_end = pace_start + timedelta(days=6)
        pace_label = "This Week"
        pct_elapsed = ((today_local - pace_start).days + 1) / 7
    elif scope == "This Month":
        pace_start = today_local.replace(day=1)
        next_m = (pace_start.replace(day=28) + timedelta(days=5)).replace(day=1)
        pace_end = next_m - timedelta(days=1)
        pace_label = "This Month"
        pct_elapsed = ((today_local - pace_start).days + 1) / ((pace_end - pace_start).days + 1)
    elif scope == "YTD":
        pace_start = date(today_local.year, 1, 1)
        pace_end = date(today_local.year, 12, 31)
        pace_label = "Year to Date"
        pct_elapsed = ((today_local - pace_start).days + 1) / 366
    elif scope == "Last 7 Days":
        pace_start = today_local - timedelta(days=6)
        pace_end = today_local
        pace_label = "Last 7 Days"
        pct_elapsed = 1.0
    elif scope == "Last 30 Days":
        pace_start = today_local - timedelta(days=29)
        pace_end = today_local
        pace_label = "Last 30 Days"
        pct_elapsed = 1.0
    else:
        pace_start, pace_end = curr_start, curr_end
        pace_label = scope_label
        total = max(1, (pace_end - pace_start).days + 1)
        elapsed = max(0, min(total, (today_local - pace_start).days + 1))
        pct_elapsed = elapsed / total

    pct_elapsed = max(0.001, min(1.0, pct_elapsed))

    df_pace = df[(df["day"] >= pace_start) & (df["day"] <= pace_end)]
    pace_rev = float(df_pace["amount_total"].sum()) if not df_pace.empty else 0.0

    # Build a baseline from the prior 3 equivalent periods (e.g., last 3 months
    # for a monthly scope) — gives a more stable reference than just last cycle.
    def _prior_avg(start, end, n=3):
        span = (end - start).days + 1
        totals = []
        for i in range(1, n + 1):
            ps = start - timedelta(days=span * i)
            pe = ps + timedelta(days=span - 1)
            r = float(df[(df["day"] >= ps) & (df["day"] <= pe)]["amount_total"].sum())
            if r > 0:
                totals.append(r)
        return sum(totals) / len(totals) if totals else 0.0

    baseline = _prior_avg(pace_start, pace_end, n=3)
    forecast = pace_rev / pct_elapsed if pct_elapsed > 0 else pace_rev
    pace_pct = (pace_rev / (baseline * pct_elapsed) * 100) if baseline else None

    # ---------- Header ----------
    st.markdown(
        "<div class='sec'><h3>Pacing & forecast</h3>"
        f"<div class='sec-sub'>{pace_label} · {pace_start.strftime('%d %b')} → "
        f"{pace_end.strftime('%d %b %Y')} · {pct_elapsed*100:.0f}% elapsed</div></div>",
        unsafe_allow_html=True,
    )

    # ---------- Pacing dial + KPI strip ----------
    col_dial, col_kpis = st.columns([2, 3])

    with col_dial:
        # Gauge: where we currently are vs baseline
        gauge_max = max(baseline * 1.4, forecast * 1.1, pace_rev * 1.1, 1)
        gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=pace_rev,
            number={"valueformat": ",.0f", "font": {"size": 30, "color": "#F4F4F5"}},
            title={"text": f"<span style='color:#A1A1AA;font-size:11px'>{pace_label} · current</span>",
                   "font": {"size": 12}},
            gauge={
                "axis": {"range": [0, gauge_max],
                         "tickfont": {"color": "#71717A", "size": 9}},
                "bar": {"color": "#19E3B6", "thickness": 0.28},
                "bgcolor": "#0E0E12",
                "borderwidth": 0,
                "steps": [
                    {"range": [0, baseline * 0.6 if baseline else gauge_max * 0.4],
                     "color": "rgba(248,113,113,0.10)"},
                    {"range": [baseline * 0.6 if baseline else gauge_max * 0.4,
                               baseline if baseline else gauge_max * 0.7],
                     "color": "rgba(245,181,68,0.10)"},
                    {"range": [baseline if baseline else gauge_max * 0.7, gauge_max],
                     "color": "rgba(34,197,94,0.10)"},
                ],
                "threshold": {
                    "line": {"color": "#A78BFA", "width": 3},
                    "thickness": 0.85,
                    "value": baseline * pct_elapsed if baseline else 0,
                },
            },
        ))
        gauge.update_layout(
            height=280, margin=dict(l=0, r=0, t=30, b=0),
            paper_bgcolor=PALETTE["surface"], font=dict(family="Inter, sans-serif"),
        )
        st.plotly_chart(gauge, use_container_width=True,
                        config={"displayModeBar": False})

    with col_kpis:
        # 4 sub-KPIs
        if pace_pct is not None:
            if pace_pct >= 105:
                pace_status = ("Ahead of pace", "kpi-delta-up", "▲")
            elif pace_pct >= 95:
                pace_status = ("On pace", "", "●")
            else:
                pace_status = ("Behind pace", "kpi-delta-dn", "▼")
        else:
            pace_status = ("No prior baseline", "", "")

        kpi_html = "<div class='kpi-grid' style='gap:10px'>"
        kpi_html += kpi_card(
            "Forecast end-of-period",
            fmt_money(forecast, CURRENCY, compact=True),
            (f"At current run-rate of {fmt_money(pace_rev/pct_elapsed if pct_elapsed else 0, CURRENCY)} "
             f"per period unit"),
            f"Baseline (avg of prior 3): {fmt_money(baseline, CURRENCY, compact=True)}" if baseline else "",
        )
        kpi_html += kpi_card(
            "Pacing status",
            f"<span class='{pace_status[1]}'>{pace_status[2]} {pace_status[0]}</span>"
            if pace_status[2] else pace_status[0],
            f"{pace_pct:.1f}% of the pro-rated baseline" if pace_pct is not None else "",
            f"Pro-rated target: {fmt_money(baseline * pct_elapsed if baseline else 0, CURRENCY, compact=True)}",
        )
        # Required daily run-rate to match baseline
        days_left = max(0, (pace_end - today_local).days)
        if days_left > 0 and baseline:
            required = (baseline - pace_rev) / days_left
            kpi_html += kpi_card(
                "Required daily run-rate",
                fmt_money(max(0, required), CURRENCY, compact=True),
                f"To match baseline by period end · {days_left} days remaining",
                "",
            )
        else:
            kpi_html += kpi_card(
                "Days remaining",
                f"{days_left:,}",
                "Period ends today" if days_left == 0 else "",
                "",
            )
        # Forecast vs baseline delta
        if baseline:
            fdiff = (forecast - baseline) / baseline * 100
            cls = "kpi-delta-up" if fdiff >= 0 else "kpi-delta-dn"
            arrow = "▲" if fdiff >= 0 else "▼"
            kpi_html += kpi_card(
                "Forecast vs baseline",
                f"<span class='{cls}'>{arrow} {abs(fdiff):.1f}%</span>",
                fmt_money(forecast - baseline, CURRENCY, compact=True) + " absolute",
                "",
            )
        kpi_html += "</div>"
        st.markdown(kpi_html, unsafe_allow_html=True)

    # ---------- Cumulative this-period vs prior baseline ----------
    st.markdown("<div class='sec' style='margin-top:18px'>"
                "<h3>Cumulative this period vs prior</h3>"
                "<div class='sec-sub'>Day-by-day cumulative revenue, this cycle (neon) "
                "vs each of the prior 3 equivalent cycles</div></div>",
                unsafe_allow_html=True)
    if baseline:
        fig = go.Figure()
        span = (pace_end - pace_start).days + 1
        # Plot the prior 3 cycles (faint) + this cycle (bright)
        for i in range(3, 0, -1):
            ps = pace_start - timedelta(days=span * i)
            pe = ps + timedelta(days=span - 1)
            d_p = df[(df["day"] >= ps) & (df["day"] <= pe)].copy()
            if d_p.empty:
                continue
            d_p["offset"] = d_p["day"].map(lambda x: (x - ps).days)
            cum = d_p.groupby("offset")["amount_total"].sum().sort_index().cumsum()
            fig.add_trace(go.Scatter(
                x=list(range(span)),
                y=[cum.get(j, cum[cum.index <= j].max() if any(cum.index <= j) else 0)
                   for j in range(span)],
                mode="lines",
                name=f"{ps.strftime('%d %b')} → {pe.strftime('%d %b')}",
                line=dict(width=1.5, color="#52525B", dash="dot"),
                opacity=0.6,
                hovertemplate="Day %{x}<br>%{y:,.0f} " + CURRENCY + "<extra></extra>",
            ))
        # This cycle
        d_cur = df[(df["day"] >= pace_start) & (df["day"] <= pace_end)].copy()
        if not d_cur.empty:
            d_cur["offset"] = d_cur["day"].map(lambda x: (x - pace_start).days)
            cum_cur = d_cur.groupby("offset")["amount_total"].sum().sort_index().cumsum()
            fig.add_trace(go.Scatter(
                x=cum_cur.index, y=cum_cur.values,
                mode="lines+markers",
                name=f"This cycle",
                line=dict(width=3, color="#19E3B6"),
                marker=dict(size=5, color="#19E3B6"),
                hovertemplate="Day %{x}<br>%{y:,.0f} " + CURRENCY + "<extra></extra>",
            ))
            # Forecast extension (dashed neon)
            if pct_elapsed < 1 and len(cum_cur) > 0:
                last_day = int(cum_cur.index.max())
                last_val = float(cum_cur.iloc[-1])
                rate = last_val / (last_day + 1) if last_day >= 0 else 0
                proj_x = list(range(last_day, span))
                proj_y = [last_val + rate * (i - last_day) for i in proj_x]
                fig.add_trace(go.Scatter(
                    x=proj_x, y=proj_y,
                    mode="lines", name="Forecast",
                    line=dict(width=2, color="#19E3B6", dash="dash"),
                    opacity=0.6, showlegend=True,
                    hovertemplate="Day %{x}<br>~%{y:,.0f} " + CURRENCY + " (forecast)<extra></extra>",
                ))
        fig.update_xaxes(title="Day of period")
        fig.update_yaxes(title=None)
        st.plotly_chart(style_fig(fig, height=360), use_container_width=True)
    else:
        st.info("Need at least one prior equivalent period for baseline comparison.")

    # ---------- 7-day momentum ----------
    st.markdown("<div class='sec' style='margin-top:14px'>"
                "<h3>7-day momentum</h3>"
                "<div class='sec-sub'>Rolling 7-day revenue · last 60 days</div></div>",
                unsafe_allow_html=True)
    cutoff = today_local - timedelta(days=59)
    d60 = df[df["day"] >= cutoff].copy()
    if not d60.empty:
        daily = d60.groupby("day")["amount_total"].sum().reset_index()
        daily = daily.sort_values("day")
        daily["rolling7"] = daily["amount_total"].rolling(7, min_periods=1).mean()
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=daily["day"], y=daily["amount_total"],
            name="Daily",
            marker=dict(color="#23232B", line=dict(width=0)),
            hovertemplate="<b>%{x|%d %b}</b><br>%{y:,.0f} " + CURRENCY + "<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=daily["day"], y=daily["rolling7"],
            mode="lines", name="7-day avg",
            line=dict(width=2.5, color="#19E3B6", shape="spline"),
            hovertemplate="<b>%{x|%d %b}</b><br>7d avg: %{y:,.0f} " + CURRENCY + "<extra></extra>",
        ))
        st.plotly_chart(style_fig(fig, height=300), use_container_width=True)


# -------- Profitability --------
with tab_profit:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='sec'><h3>Profitability</h3>"
        f"<div class='sec-sub'>{scope_label} · gross profit and margin %, "
        "from Odoo's per-order margin field (real cost data)</div></div>",
        unsafe_allow_html=True,
    )

    if df_curr.empty:
        st.info("No data in selected window.")
    else:
        # ---- KPI strip ----
        rev_p = float(df_curr["amount_total"].sum())
        profit_p = float(df_curr["margin"].sum())
        margin_pct = (profit_p / rev_p * 100) if rev_p else 0
        cogs_p = rev_p - profit_p

        prev_rev_p = float(df_prev["amount_total"].sum()) if not df_prev.empty else 0
        prev_profit_p = float(df_prev["margin"].sum()) if not df_prev.empty else 0
        prev_margin_pct = (prev_profit_p / prev_rev_p * 100) if prev_rev_p else 0

        # Best & worst channel by margin
        ch_grp = (df_curr.groupby("channel")
                  .agg(rev=("amount_total", "sum"),
                       prof=("margin", "sum"),
                       n=("amount_total", "count"))
                  .reset_index())
        ch_grp["gm_pct"] = ch_grp.apply(
            lambda r: r["prof"] / r["rev"] * 100 if r["rev"] else 0, axis=1
        )
        ch_grp = ch_grp.sort_values("prof", ascending=False)

        kpi_html = "<div class='kpi-grid'>"
        kpi_html += kpi_card(
            "Gross profit",
            fmt_money(profit_p, CURRENCY, compact=True),
            delta_html(profit_p, prev_profit_p, "vs prior period"),
            f"Prior: {fmt_money(prev_profit_p, CURRENCY, compact=True)}",
        )
        kpi_html += kpi_card(
            "Gross margin",
            f"{margin_pct:.1f}%",
            delta_html(margin_pct, prev_margin_pct, "ppts vs prior") if prev_margin_pct else
            "<span style='color:#71717A'>no prior</span>",
            f"Prior: {prev_margin_pct:.1f}%" if prev_margin_pct else "",
        )
        kpi_html += kpi_card(
            "COGS",
            fmt_money(cogs_p, CURRENCY, compact=True),
            f"<span style='color:#71717A'>{(cogs_p/rev_p*100 if rev_p else 0):.1f}% of revenue</span>",
            "",
        )
        if not ch_grp.empty:
            best = ch_grp.sort_values("gm_pct", ascending=False).iloc[0]
            kpi_html += kpi_card(
                "Highest-margin channel",
                f"<span style='color:#19E3B6'>{best['channel']}</span>",
                f"<b>{best['gm_pct']:.1f}%</b> margin · "
                f"{fmt_money(best['prof'], CURRENCY, compact=True)} profit",
                "",
            )
        kpi_html += "</div>"
        st.markdown(kpi_html, unsafe_allow_html=True)

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

        # ---- Charts row ----
        c1, c2 = st.columns([3, 2])

        with c1:
            st.markdown("<div class='sec'><h3>Profit and margin by channel</h3>"
                        f"<div class='sec-sub'>{scope_label}</div></div>",
                        unsafe_allow_html=True)
            ch_sorted = ch_grp.sort_values("prof", ascending=True)
            ch_colors = channel_colors_for(ch_sorted["channel"])
            fig = go.Figure()
            fig.add_trace(go.Bar(
                y=ch_sorted["channel"], x=ch_sorted["prof"],
                orientation="h",
                marker=dict(color=ch_colors, line=dict(width=0)),
                text=[f"{p:,.0f}  ({m:.1f}%)" for p, m
                      in zip(ch_sorted["prof"], ch_sorted["gm_pct"])],
                texttemplate="%{text}",
                textposition="outside",
                textfont=dict(color=PALETTE["text_dim"], size=11),
                cliponaxis=False,
                hovertemplate="<b>%{y}</b><br>"
                              "Profit: %{x:,.0f} " + CURRENCY + "<br>"
                              "Margin: %{customdata:.1f}%<extra></extra>",
                customdata=ch_sorted["gm_pct"],
            ))
            st.plotly_chart(style_fig(fig, height=380, show_legend=False),
                            use_container_width=True)

        with c2:
            st.markdown("<div class='sec'><h3>Revenue split</h3>"
                        "<div class='sec-sub'>Gross profit vs cost of goods</div></div>",
                        unsafe_allow_html=True)
            fig = go.Figure(data=[go.Pie(
                labels=["Gross profit", "COGS"],
                values=[max(profit_p, 0), max(cogs_p, 0)],
                hole=0.7,
                marker=dict(colors=["#19E3B6", "#3F3F46"],
                            line=dict(color=PALETTE["surface"], width=3)),
                texttemplate="%{value:,.0f}<br>%{percent}",
                textfont=dict(size=12, color=PALETTE["text"]),
                hovertemplate="<b>%{label}</b><br>"
                              "%{value:,.0f} " + CURRENCY +
                              "<br>%{percent}<extra></extra>",
            )])
            fig.update_layout(annotations=[dict(
                text=f"<b>{margin_pct:.1f}%</b>"
                     f"<br><span style='font-size:10px;color:#A1A1AA'>Margin</span>",
                showarrow=False, font=dict(size=14, color=PALETTE["text"]))])
            st.plotly_chart(style_fig(fig, height=380), use_container_width=True)

        # ---- Profit trend over time ----
        st.markdown("<div class='sec' style='margin-top:14px'>"
                    "<h3>Profit and margin trend</h3>"
                    f"<div class='sec-sub'>{scope_label} · daily gross profit "
                    "(bars) and rolling 7-day margin % (line)</div></div>",
                    unsafe_allow_html=True)
        if len(df_curr) > 0:
            daily = (df_curr.groupby("day")
                     .agg(rev=("amount_total", "sum"),
                          prof=("margin", "sum"),
                          n=("amount_total", "count"))
                     .sort_index().reset_index())
            daily["gm"] = daily.apply(
                lambda r: r["prof"] / r["rev"] * 100 if r["rev"] else 0, axis=1
            )
            daily["gm_roll"] = daily["gm"].rolling(7, min_periods=1).mean()

            from plotly.subplots import make_subplots
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            show_lbl = len(daily) <= 45
            fig.add_trace(go.Bar(
                x=daily["day"], y=daily["prof"],
                name="Daily profit",
                marker=dict(color="#19E3B6", line=dict(width=0)),
                text=daily["prof"] if show_lbl else None,
                texttemplate="%{text:,.0f}" if show_lbl else None,
                textposition="outside",
                textfont=dict(color=PALETTE["text_dim"], size=10),
                cliponaxis=False,
                hovertemplate="<b>%{x|%d %b}</b><br>Profit: %{y:,.0f} " + CURRENCY +
                              "<extra></extra>",
            ), secondary_y=False)
            fig.add_trace(go.Scatter(
                x=daily["day"], y=daily["gm_roll"],
                name="7-day margin %",
                mode="lines",
                line=dict(color="#F5B544", width=2.5, shape="spline"),
                hovertemplate="<b>%{x|%d %b}</b><br>Margin %{y:.1f}%<extra></extra>",
            ), secondary_y=True)
            fig.update_yaxes(title=None, secondary_y=False)
            fig.update_yaxes(title="margin %", secondary_y=True,
                             range=[0, max(80, daily["gm_roll"].max() * 1.1) if not daily.empty else 100],
                             gridcolor=PALETTE["border"], showgrid=False,
                             tickfont=dict(color="#F5B544", size=11))
            st.plotly_chart(style_fig(fig, height=340), use_container_width=True)

        # ---- Per-channel detail table ----
        st.markdown("<div class='sec' style='margin-top:14px'>"
                    "<h3>Channel profitability detail</h3></div>",
                    unsafe_allow_html=True)
        tbl = ch_grp.copy()
        tbl["share_of_rev"] = tbl["rev"] / rev_p * 100 if rev_p else 0
        tbl["share_of_profit"] = tbl["prof"] / profit_p * 100 if profit_p else 0
        tbl = tbl[["channel", "n", "rev", "prof", "gm_pct",
                   "share_of_rev", "share_of_profit"]]
        tbl.columns = ["Channel", "Orders", f"Revenue ({CURRENCY})",
                       f"Profit ({CURRENCY})", "Margin %",
                       "% of revenue", "% of profit"]
        st.dataframe(
            tbl, use_container_width=True, hide_index=True,
            column_config={
                f"Revenue ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                f"Profit ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                "Margin %": st.column_config.NumberColumn(format="%.1f%%"),
                "% of revenue": st.column_config.NumberColumn(format="%.1f%%"),
                "% of profit": st.column_config.NumberColumn(format="%.1f%%"),
                "Orders": st.column_config.NumberColumn(format="%,d"),
            },
        )

        # ---- Top profit drivers (customers & salespeople) ----
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("<div class='sec'><h3>Top customers by profit</h3></div>",
                        unsafe_allow_html=True)
            top_c = (df_curr.groupby("customer")
                     .agg(rev=("amount_total", "sum"),
                          prof=("margin", "sum"))
                     .reset_index())
            top_c["gm_pct"] = top_c.apply(
                lambda r: r["prof"] / r["rev"] * 100 if r["rev"] else 0, axis=1
            )
            top_c = top_c.sort_values("prof", ascending=False).head(15)
            top_c.columns = ["Customer", f"Revenue ({CURRENCY})",
                             f"Profit ({CURRENCY})", "Margin %"]
            st.dataframe(
                top_c, use_container_width=True, hide_index=True, height=460,
                column_config={
                    f"Revenue ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                    f"Profit ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                    "Margin %": st.column_config.NumberColumn(format="%.1f%%"),
                },
            )
        with c2:
            st.markdown("<div class='sec'><h3>Top salespeople by profit</h3></div>",
                        unsafe_allow_html=True)
            top_s = (df_curr.groupby("salesperson")
                     .agg(rev=("amount_total", "sum"),
                          prof=("margin", "sum"))
                     .reset_index())
            top_s["gm_pct"] = top_s.apply(
                lambda r: r["prof"] / r["rev"] * 100 if r["rev"] else 0, axis=1
            )
            top_s = top_s.sort_values("prof", ascending=False).head(15)
            top_s.columns = ["Salesperson", f"Revenue ({CURRENCY})",
                             f"Profit ({CURRENCY})", "Margin %"]
            st.dataframe(
                top_s, use_container_width=True, hide_index=True, height=460,
                column_config={
                    f"Revenue ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                    f"Profit ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                    "Margin %": st.column_config.NumberColumn(format="%.1f%%"),
                },
            )


# -------- Products / SKUs --------
with tab_sku:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='sec'><h3>Products &amp; SKUs</h3>"
        f"<div class='sec-sub'>{scope_label} · what's actually selling, "
        "from real Odoo order lines (sale.order.line + pos.order.line)</div></div>",
        unsafe_allow_html=True,
    )

    if df_curr.empty:
        st.info("No data in selected window.")
    else:
        # Fetch lines for the active scope window
        sku_start_utc, sku_end_utc = _date_window_utc(curr_start, curr_end, TZ)
        with st.spinner("Loading product detail..."):
            sku_rows = fetch_order_lines_window(
                sku_start_utc.strftime("%Y-%m-%d %H:%M:%S"),
                sku_end_utc.strftime("%Y-%m-%d %H:%M:%S"),
                hist_bucket,
            )

        if not sku_rows:
            st.info("No order lines available for this window.")
        else:
            sku_df = pd.DataFrame(sku_rows)

            # ---- KPI strip ----
            unique_skus = sku_df["product_id"].nunique()
            total_units = float(sku_df["qty"].sum())
            total_rev = float(sku_df["revenue"].sum())
            total_margin = float(sku_df["margin"].sum())
            avg_margin_pct = (total_margin / total_rev * 100) if total_rev else 0
            top_sku_row = (sku_df.groupby(["product_id", "product_name"])
                           .agg(rev=("revenue", "sum"))
                           .reset_index().sort_values("rev", ascending=False))
            top_sku_name = top_sku_row.iloc[0]["product_name"] if not top_sku_row.empty else "—"
            top_sku_rev = top_sku_row.iloc[0]["rev"] if not top_sku_row.empty else 0

            kpi_html = "<div class='kpi-grid'>"
            kpi_html += kpi_card(
                "Unique SKUs sold",
                f"{unique_skus:,}",
                f"<span style='color:#71717A'>across {len(sku_df):,} order lines</span>",
                "",
            )
            kpi_html += kpi_card(
                "Total units",
                f"{total_units:,.0f}",
                f"<span style='color:#71717A'>summed across all SKUs</span>",
                "",
            )
            kpi_html += kpi_card(
                "Lines revenue",
                fmt_money(total_rev, CURRENCY, compact=True),
                f"<span style='color:#71717A'>at {avg_margin_pct:.1f}% gross margin</span>",
                f"Profit: {fmt_money(total_margin, CURRENCY, compact=True)}",
            )
            short_top = (top_sku_name[:38] + "…") if len(top_sku_name) > 40 else top_sku_name
            kpi_html += kpi_card(
                "Best-selling SKU",
                f"<span style='color:#19E3B6;font-size:18px'>{short_top}</span>",
                f"<b>{fmt_money(top_sku_rev, CURRENCY, compact=True)}</b>"
                f" <span style='color:#71717A'>· "
                f"{(top_sku_rev/total_rev*100 if total_rev else 0):.1f}% of revenue</span>",
                "",
            )
            kpi_html += "</div>"
            st.markdown(kpi_html, unsafe_allow_html=True)

            st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

            # ---- Top SKUs by revenue ----
            agg = (sku_df.groupby(["product_id", "product_name"])
                   .agg(units=("qty", "sum"),
                        revenue=("revenue", "sum"),
                        margin=("margin", "sum"),
                        lines=("revenue", "count"))
                   .reset_index())
            agg["margin_pct"] = agg.apply(
                lambda r: r["margin"] / r["revenue"] * 100 if r["revenue"] else 0,
                axis=1,
            )
            agg["share_rev"] = agg["revenue"] / total_rev * 100 if total_rev else 0

            c1, c2 = st.columns([3, 2])
            with c1:
                st.markdown("<div class='sec'><h3>Top 15 SKUs by revenue</h3></div>",
                            unsafe_allow_html=True)
                top15 = agg.sort_values("revenue", ascending=False).head(15)
                # Trim long names
                top15_disp = top15.copy()
                top15_disp["short_name"] = top15_disp["product_name"].apply(
                    lambda s: (s[:50] + "…") if len(s) > 52 else s
                )
                fig = go.Figure(go.Bar(
                    y=top15_disp["short_name"][::-1],
                    x=top15_disp["revenue"][::-1],
                    orientation="h",
                    marker=dict(
                        color=top15_disp["revenue"][::-1],
                        colorscale=[[0, "#0E5A4A"], [1, "#19E3B6"]],
                        line=dict(width=0),
                    ),
                    text=top15_disp["revenue"][::-1],
                    texttemplate="%{text:,.0f}",
                    textposition="outside",
                    textfont=dict(color=PALETTE["text_dim"], size=10),
                    cliponaxis=False,
                    customdata=top15_disp["margin_pct"][::-1],
                    hovertemplate="<b>%{y}</b><br>"
                                  "Revenue: %{x:,.0f} " + CURRENCY + "<br>"
                                  "Margin: %{customdata:.1f}%<extra></extra>",
                ))
                st.plotly_chart(style_fig(fig, height=520, show_legend=False),
                                use_container_width=True)
            with c2:
                st.markdown("<div class='sec'><h3>Revenue concentration</h3>"
                            "<div class='sec-sub'>Top X SKUs as % of revenue</div></div>",
                            unsafe_allow_html=True)
                # Build concentration buckets
                rev_sorted = agg.sort_values("revenue", ascending=False)["revenue"].reset_index(drop=True)
                buckets = []
                for n, label in [(5, "Top 5"), (10, "Top 6–10"),
                                  (25, "Top 11–25"), (50, "Top 26–50")]:
                    if n == 5:
                        b = rev_sorted.head(5).sum()
                    else:
                        prior = {10: 5, 25: 10, 50: 25}[n]
                        b = rev_sorted.iloc[prior:n].sum() if len(rev_sorted) > prior else 0
                    buckets.append((label, b))
                rest = rev_sorted.iloc[50:].sum() if len(rev_sorted) > 50 else 0
                buckets.append(("Rest", rest))
                fig = go.Figure(go.Pie(
                    labels=[b[0] for b in buckets],
                    values=[b[1] for b in buckets],
                    hole=0.65,
                    marker=dict(colors=["#19E3B6", "#38BDF8", "#A78BFA",
                                        "#F5B544", "#52525B"],
                                line=dict(color=PALETTE["surface"], width=3)),
                    texttemplate="%{value:,.0f}<br>%{percent}",
                    textfont=dict(size=11, color=PALETTE["text"]),
                    hovertemplate="<b>%{label}</b><br>%{value:,.0f} " + CURRENCY +
                                  "<br>%{percent}<extra></extra>",
                ))
                fig.update_layout(annotations=[dict(
                    text=f"<b>{unique_skus}</b>"
                         f"<br><span style='font-size:10px;color:#A1A1AA'>SKUs</span>",
                    showarrow=False, font=dict(size=14, color=PALETTE["text"]))])
                st.plotly_chart(style_fig(fig, height=520),
                                use_container_width=True)

            # ---- Revenue vs margin scatter (find your stars and dogs) ----
            st.markdown("<div class='sec' style='margin-top:14px'>"
                        "<h3>Revenue vs margin</h3>"
                        "<div class='sec-sub'>Top-right = high volume + high margin (stars). "
                        "Bottom-right = high volume but thin margin (re-pricing candidates).</div>"
                        "</div>",
                        unsafe_allow_html=True)
            scatter_df = agg[agg["revenue"] > 0].copy()
            # Limit to top 50 by revenue to keep readable
            scatter_df = scatter_df.sort_values("revenue", ascending=False).head(50)
            fig = go.Figure(go.Scatter(
                x=scatter_df["revenue"],
                y=scatter_df["margin_pct"],
                mode="markers",
                marker=dict(
                    size=(scatter_df["units"] / scatter_df["units"].max() * 30 + 6
                          if scatter_df["units"].max() > 0 else 10),
                    color=scatter_df["margin_pct"],
                    colorscale=[[0, "#F87171"], [0.5, "#F5B544"], [1, "#19E3B6"]],
                    showscale=True,
                    colorbar=dict(title="Margin %", thickness=8,
                                  tickfont=dict(color="#A1A1AA", size=9)),
                    line=dict(width=0.5, color="#23232B"),
                    opacity=0.85,
                ),
                text=scatter_df["product_name"],
                hovertemplate="<b>%{text}</b><br>"
                              "Revenue: %{x:,.0f} " + CURRENCY + "<br>"
                              "Margin: %{y:.1f}%<br>"
                              "Units: %{customdata:,.0f}<extra></extra>",
                customdata=scatter_df["units"],
            ))
            fig.update_xaxes(title=f"Revenue ({CURRENCY})")
            fig.update_yaxes(title="Margin %")
            st.plotly_chart(style_fig(fig, height=440, show_legend=False),
                            use_container_width=True)

            # ---- Detailed table ----
            st.markdown("<div class='sec' style='margin-top:14px'>"
                        "<h3>All products — detailed</h3>"
                        f"<div class='sec-sub'>{unique_skus:,} SKUs · sortable, exportable</div>"
                        "</div>",
                        unsafe_allow_html=True)
            tbl = agg.sort_values("revenue", ascending=False).copy()
            tbl = tbl[["product_name", "units", "lines", "revenue",
                       "margin", "margin_pct", "share_rev"]]
            tbl.columns = ["Product", "Units", "Order lines",
                           f"Revenue ({CURRENCY})", f"Profit ({CURRENCY})",
                           "Margin %", "% of revenue"]
            st.dataframe(
                tbl, use_container_width=True, hide_index=True, height=520,
                column_config={
                    "Units": st.column_config.NumberColumn(format="%,.0f"),
                    "Order lines": st.column_config.NumberColumn(format="%,d"),
                    f"Revenue ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                    f"Profit ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                    "Margin %": st.column_config.NumberColumn(format="%.1f%%"),
                    "% of revenue": st.column_config.NumberColumn(format="%.1f%%"),
                },
            )

            # CSV export
            csv_bytes = tbl.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="◌  Download SKUs as CSV",
                data=csv_bytes,
                file_name=f"fyxx-skus-{curr_start}-to-{curr_end}.csv",
                mime="text/csv",
                use_container_width=False,
            )

            # ---- Basket analysis (top SKU pairs in the same order) ----
            st.markdown("<div class='sec' style='margin-top:14px'>"
                        "<h3>Often bought together</h3>"
                        "<div class='sec-sub'>SKU pairs that appeared in the same order most often</div>"
                        "</div>",
                        unsafe_allow_html=True)
            try:
                from collections import Counter
                pair_counter = Counter()
                # Group product_ids by order_id, then count pairs
                grp = sku_df.groupby("order_id")["product_id"].apply(
                    lambda s: list(set(s.dropna().astype(int).tolist()))
                )
                # Limit basket combinatorics to orders with <= 12 distinct products
                for prods in grp:
                    if 2 <= len(prods) <= 12:
                        prods = sorted(prods)
                        for i in range(len(prods)):
                            for j in range(i + 1, len(prods)):
                                pair_counter[(prods[i], prods[j])] += 1
                if pair_counter:
                    name_lookup = dict(zip(sku_df["product_id"], sku_df["product_name"]))
                    top_pairs = pair_counter.most_common(15)
                    pair_rows = []
                    for (a, b), n in top_pairs:
                        pair_rows.append({
                            "Pair": f"{name_lookup.get(a, '?')[:35]}  ↔  {name_lookup.get(b, '?')[:35]}",
                            "Times bought together": n,
                        })
                    pair_df = pd.DataFrame(pair_rows)
                    st.dataframe(
                        pair_df, use_container_width=True, hide_index=True,
                        column_config={
                            "Times bought together":
                                st.column_config.NumberColumn(format="%,d"),
                        },
                    )
                else:
                    st.caption("Not enough multi-line orders in this window for basket analysis.")
            except Exception as exc:
                st.caption(f"Basket analysis skipped: {exc}")


# -------- Loss Orders --------
with tab_loss:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='sec'><h3>Orders sold at a loss</h3>"
        f"<div class='sec-sub'>{scope_label} · "
        "every order whose Odoo margin is negative — sorted worst first</div></div>",
        unsafe_allow_html=True,
    )

    if df_curr.empty or "margin" not in df_curr.columns:
        st.info("No data in selected window.")
    else:
        losses_df = df_curr[df_curr["margin"] < 0].copy()

        if losses_df.empty:
            st.markdown(
                "<div class='brief-card'><p class='brief-callout brief-good'>"
                "No loss-making orders in this period for the selected channels. "
                "Every order had a positive (or zero) gross margin."
                "</p></div>",
                unsafe_allow_html=True,
            )
        else:
            # Compute extras for the detail view
            losses_df = losses_df.sort_values("margin")  # most negative first
            losses_df["revenue"] = losses_df["amount_total"]
            losses_df["cost"] = losses_df["revenue"] - losses_df["margin"]
            losses_df["margin_pct"] = losses_df.apply(
                lambda r: r["margin"] / r["revenue"] * 100 if r["revenue"] else 0,
                axis=1,
            )

            # ---- KPI strip ----
            n_loss = len(losses_df)
            n_total = len(df_curr)
            loss_share = n_loss / n_total * 100 if n_total else 0
            total_loss = float(losses_df["margin"].sum())  # negative number
            total_loss_rev = float(losses_df["revenue"].sum())
            worst_order = losses_df.iloc[0]

            kpi_html = "<div class='kpi-grid'>"
            kpi_html += kpi_card(
                "Loss-making orders",
                f"{n_loss:,}",
                f"<span style='color:#F87171;font-weight:600'>{loss_share:.1f}%</span> "
                f"<span style='color:#71717A'>of {n_total:,} total orders</span>",
                "",
            )
            kpi_html += kpi_card(
                "Total loss",
                f"<span style='color:#F87171'>"
                f"{fmt_money(abs(total_loss), CURRENCY, compact=True)}</span>",
                f"<span style='color:#71717A'>across "
                f"{fmt_money(total_loss_rev, CURRENCY, compact=True)} of revenue "
                f"sold below cost</span>",
                "",
            )
            kpi_html += kpi_card(
                "Worst single order",
                f"<span style='color:#F87171'>"
                f"{fmt_money(abs(worst_order['margin']), CURRENCY)}</span>",
                f"<b>{worst_order['name']}</b> · {worst_order['customer']}",
                f"<span style='color:#71717A'>{worst_order['channel']} · "
                f"{worst_order['margin_pct']:.1f}% margin</span>",
            )
            avg_loss = total_loss / n_loss if n_loss else 0
            kpi_html += kpi_card(
                "Average loss per order",
                f"<span style='color:#F87171'>"
                f"{fmt_money(abs(avg_loss), CURRENCY)}</span>",
                f"<span style='color:#71717A'>per loss-making order</span>",
                "",
            )
            kpi_html += "</div>"
            st.markdown(kpi_html, unsafe_allow_html=True)

            st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

            # ---- Charts row ----
            c1, c2 = st.columns([3, 2])

            with c1:
                st.markdown("<div class='sec'><h3>Loss by channel</h3>"
                            "<div class='sec-sub'>Total negative margin per channel</div></div>",
                            unsafe_allow_html=True)
                ch_loss = (losses_df.groupby("channel")
                           .agg(loss=("margin", "sum"),
                                n=("margin", "count"))
                           .reset_index()
                           .sort_values("loss"))  # most negative first
                ch_loss["abs_loss"] = ch_loss["loss"].abs()
                fig = go.Figure(go.Bar(
                    y=ch_loss["channel"],
                    x=ch_loss["abs_loss"],
                    orientation="h",
                    marker=dict(
                        color=ch_loss["abs_loss"],
                        colorscale=[[0, "#7F1D1D"], [1, "#F87171"]],
                        line=dict(width=0),
                    ),
                    text=[f"{v:,.0f}  ({n} orders)"
                          for v, n in zip(ch_loss["abs_loss"], ch_loss["n"])],
                    texttemplate="%{text}",
                    textposition="outside",
                    textfont=dict(color=PALETTE["text_dim"], size=11),
                    cliponaxis=False,
                    hovertemplate="<b>%{y}</b><br>"
                                  "Loss: %{x:,.0f} " + CURRENCY + "<extra></extra>",
                ))
                st.plotly_chart(style_fig(fig, height=360, show_legend=False),
                                use_container_width=True)

            with c2:
                st.markdown("<div class='sec'><h3>Loss share</h3>"
                            "<div class='sec-sub'>Where the bleed is concentrated</div></div>",
                            unsafe_allow_html=True)
                ch_loss_pie = ch_loss.copy()
                fig = go.Figure(data=[go.Pie(
                    labels=ch_loss_pie["channel"],
                    values=ch_loss_pie["abs_loss"],
                    hole=0.65,
                    marker=dict(colors=channel_colors_for(ch_loss_pie["channel"]),
                                line=dict(color=PALETTE["surface"], width=3)),
                    texttemplate="%{value:,.0f}<br>%{percent}",
                    textfont=dict(size=11, color=PALETTE["text"]),
                    hovertemplate="<b>%{label}</b><br>"
                                  "%{value:,.0f} " + CURRENCY +
                                  "<br>%{percent}<extra></extra>",
                )])
                fig.update_layout(annotations=[dict(
                    text=f"<b style='color:#F87171'>"
                         f"{fmt_money(abs(total_loss), CURRENCY, compact=True)}</b>"
                         f"<br><span style='font-size:10px;color:#A1A1AA'>Total loss</span>",
                    showarrow=False,
                    font=dict(size=14, color=PALETTE["text"]))])
                st.plotly_chart(style_fig(fig, height=360),
                                use_container_width=True)

            # ---- Loss trend over time ----
            st.markdown("<div class='sec' style='margin-top:14px'>"
                        "<h3>Loss trend</h3>"
                        f"<div class='sec-sub'>Daily total loss · {scope_label}</div></div>",
                        unsafe_allow_html=True)
            daily_loss = (losses_df.groupby("day")
                          .agg(loss=("margin", "sum"),
                               n=("margin", "count"))
                          .reset_index()
                          .sort_values("day"))
            daily_loss["abs_loss"] = daily_loss["loss"].abs()
            if not daily_loss.empty:
                show_lbl = len(daily_loss) <= 45
                fig = go.Figure(go.Bar(
                    x=daily_loss["day"], y=daily_loss["abs_loss"],
                    text=daily_loss["abs_loss"] if show_lbl else None,
                    texttemplate="%{text:,.0f}" if show_lbl else None,
                    textposition="outside",
                    textfont=dict(color="#F87171", size=10),
                    cliponaxis=False,
                    marker=dict(color="#F87171", line=dict(width=0)),
                    customdata=daily_loss["n"],
                    hovertemplate="<b>%{x|%d %b %Y}</b><br>"
                                  "Loss: %{y:,.0f} " + CURRENCY + "<br>"
                                  "%{customdata} orders<extra></extra>",
                ))
                st.plotly_chart(style_fig(fig, height=300, show_legend=False),
                                use_container_width=True)

            # ---- Top loss-making customers / salespeople ----
            l1, l2 = st.columns(2)
            with l1:
                st.markdown("<div class='sec'><h3>Worst customers</h3>"
                            "<div class='sec-sub'>Cumulative loss across orders</div></div>",
                            unsafe_allow_html=True)
                cust_loss = (losses_df.groupby("customer")
                             .agg(loss=("margin", "sum"),
                                  rev=("revenue", "sum"),
                                  n=("margin", "count"))
                             .reset_index())
                cust_loss["abs_loss"] = cust_loss["loss"].abs()
                cust_loss = cust_loss.sort_values("loss").head(15)
                cust_loss = cust_loss[["customer", "n", "rev", "abs_loss"]]
                cust_loss.columns = ["Customer", "Loss orders",
                                     f"Revenue ({CURRENCY})",
                                     f"Loss ({CURRENCY})"]
                st.dataframe(
                    cust_loss, use_container_width=True, hide_index=True, height=460,
                    column_config={
                        f"Revenue ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                        f"Loss ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                        "Loss orders": st.column_config.NumberColumn(format="%,d"),
                    },
                )
            with l2:
                st.markdown("<div class='sec'><h3>Salespeople with most losses</h3></div>",
                            unsafe_allow_html=True)
                sp_loss = (losses_df.groupby("salesperson")
                           .agg(loss=("margin", "sum"),
                                rev=("revenue", "sum"),
                                n=("margin", "count"))
                           .reset_index())
                sp_loss["abs_loss"] = sp_loss["loss"].abs()
                sp_loss = sp_loss.sort_values("loss").head(15)
                sp_loss = sp_loss[["salesperson", "n", "rev", "abs_loss"]]
                sp_loss.columns = ["Salesperson", "Loss orders",
                                   f"Revenue ({CURRENCY})",
                                   f"Loss ({CURRENCY})"]
                st.dataframe(
                    sp_loss, use_container_width=True, hide_index=True, height=460,
                    column_config={
                        f"Revenue ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                        f"Loss ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                        "Loss orders": st.column_config.NumberColumn(format="%,d"),
                    },
                )

            # ---- Detailed loss-orders table ----
            st.markdown("<div class='sec' style='margin-top:14px'>"
                        "<h3>Every loss-making order — detailed</h3>"
                        f"<div class='sec-sub'>{n_loss:,} orders · sorted by largest loss first · "
                        "click any column header to re-sort</div></div>",
                        unsafe_allow_html=True)

            # Optional channel filter just for this table (in addition to top slicer)
            chan_options = sorted(losses_df["channel"].dropna().unique().tolist())
            if len(chan_options) > 1:
                pick = st.multiselect(
                    "Filter detail by channel",
                    chan_options, default=chan_options,
                    label_visibility="collapsed", key="loss_detail_ch",
                )
                if pick:
                    losses_view = losses_df[losses_df["channel"].isin(pick)]
                else:
                    losses_view = losses_df
            else:
                losses_view = losses_df

            losses_view = losses_view.copy()
            losses_view["date"] = losses_view["dt_local"].dt.strftime("%Y-%m-%d %H:%M")
            losses_view["abs_loss"] = losses_view["margin"].abs()
            detail = losses_view[[
                "name", "date", "channel", "source", "customer", "salesperson",
                "revenue", "cost", "abs_loss", "margin_pct", "state"
            ]].copy()
            detail.columns = [
                "Reference", "Date", "Channel", "Source", "Customer",
                "Salesperson", f"Revenue ({CURRENCY})", f"Cost ({CURRENCY})",
                f"Loss ({CURRENCY})", "Margin %", "State"
            ]
            st.dataframe(
                detail, use_container_width=True, hide_index=True, height=620,
                column_config={
                    f"Revenue ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                    f"Cost ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                    f"Loss ({CURRENCY})": st.column_config.NumberColumn(
                        format="%,.0f",
                        help="Absolute amount lost (negative margin)"),
                    "Margin %": st.column_config.NumberColumn(format="%.1f%%"),
                },
            )

            # ---- CSV download ----
            csv_bytes = detail.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="◌  Download loss orders as CSV",
                data=csv_bytes,
                file_name=f"fyxx-loss-orders-{curr_start}-to-{curr_end}.csv",
                mime="text/csv",
                use_container_width=False,
            )


# -------- Alerts & Anomalies --------
with tab_alerts:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='sec'><h3>Anomalies & alerts</h3>"
        f"<div class='sec-sub'>{scope_label} · auto-detected outliers and risk signals</div></div>",
        unsafe_allow_html=True,
    )

    alerts = []  # list of (severity, icon, title, body)

    if not df_curr.empty:
        # 1) Statistical day outliers (>2σ from mean of last 60 days baseline)
        cutoff = today_local - timedelta(days=59)
        baseline_df = df[df["day"] >= cutoff]
        if not baseline_df.empty:
            daily_b = baseline_df.groupby("day")["amount_total"].sum()
            mean_b, std_b = daily_b.mean(), daily_b.std()
            curr_daily = df_curr.groupby("day")["amount_total"].sum()
            for d_, v in curr_daily.items():
                if std_b > 0:
                    z = (v - mean_b) / std_b
                    if z >= 2:
                        alerts.append(("good", "▲",
                            f"Outlier high day · {d_.strftime('%a %d %b')}",
                            f"Revenue of <b>{fmt_money(v, CURRENCY, compact=True)}</b> "
                            f"is <b>{z:.1f}σ above</b> the 60-day mean of "
                            f"{fmt_money(mean_b, CURRENCY, compact=True)}."))
                    elif z <= -2:
                        alerts.append(("bad", "▼",
                            f"Outlier low day · {d_.strftime('%a %d %b')}",
                            f"Revenue of <b>{fmt_money(v, CURRENCY, compact=True)}</b> "
                            f"is <b>{abs(z):.1f}σ below</b> the 60-day mean."))

        # 2) Concentration risk
        cust_rev = df_curr.groupby("customer")["amount_total"].sum().sort_values(ascending=False)
        total = float(cust_rev.sum())
        if len(cust_rev) > 0 and total > 0:
            top_share = cust_rev.iloc[0] / total * 100
            if top_share >= 25:
                alerts.append(("warn", "◆",
                    f"Customer concentration risk",
                    f"<b>{cust_rev.index[0]}</b> accounts for "
                    f"<b>{top_share:.1f}%</b> of revenue this period — "
                    f"single-customer dependency."))
            top10_share = cust_rev.head(10).sum() / total * 100
            if top10_share >= 70 and len(cust_rev) >= 10:
                alerts.append(("warn", "◆",
                    f"Top-10 concentration",
                    f"Top 10 customers drive <b>{top10_share:.1f}%</b> "
                    f"of revenue — diversification opportunity."))

        # 3) Channel deceleration vs baseline
        ch_curr_s = df_curr.groupby("channel")["amount_total"].sum()
        # Baseline: prior 4 equivalent periods averaged
        span = (curr_end - curr_start).days + 1
        ch_base = {}
        for ch in ch_curr_s.index:
            totals = []
            for i in range(1, 5):
                ps = curr_start - timedelta(days=span * i)
                pe = ps + timedelta(days=span - 1)
                d_p = df[(df["day"] >= ps) & (df["day"] <= pe) & (df["channel"] == ch)]
                if not d_p.empty:
                    totals.append(float(d_p["amount_total"].sum()))
            ch_base[ch] = sum(totals) / len(totals) if totals else 0
        for ch, v in ch_curr_s.items():
            base = ch_base.get(ch, 0)
            if base > 0:
                drop = (v - base) / base * 100
                if drop <= -25:
                    alerts.append(("bad", "▼",
                        f"{ch} significantly down",
                        f"Revenue of <b>{fmt_money(v, CURRENCY, compact=True)}</b> "
                        f"is <b>{abs(drop):.1f}% below</b> the 4-period baseline of "
                        f"{fmt_money(base, CURRENCY, compact=True)}."))
                elif drop >= 30:
                    alerts.append(("good", "▲",
                        f"{ch} significantly up",
                        f"Revenue of <b>{fmt_money(v, CURRENCY, compact=True)}</b> "
                        f"is <b>{drop:.1f}% above</b> the 4-period baseline of "
                        f"{fmt_money(base, CURRENCY, compact=True)}."))

        # 4) At-risk regular customers (active before, silent recently)
        # Define: customer with 3+ orders in days [-90, -30] but 0 orders in days [-30, 0]
        ref_start = today_local - timedelta(days=90)
        ref_mid = today_local - timedelta(days=30)
        prior_window = df[(df["day"] >= ref_start) & (df["day"] < ref_mid)]
        recent_window = df[(df["day"] >= ref_mid) & (df["day"] <= today_local)]
        if not prior_window.empty:
            prior_orders = prior_window.groupby("customer").size()
            regulars = prior_orders[prior_orders >= 3].index
            recent_active = set(recent_window["customer"].unique())
            at_risk = [c for c in regulars if c not in recent_active]
            if at_risk:
                # Show top 5 by their prior-period revenue
                ar_rev = (prior_window[prior_window["customer"].isin(at_risk)]
                          .groupby("customer")["amount_total"].sum()
                          .sort_values(ascending=False))
                top_at_risk = ar_rev.head(5)
                names_html = "<br>".join(
                    f"&nbsp;&nbsp;• {c} — was {fmt_money(v, CURRENCY, compact=True)}"
                    for c, v in top_at_risk.items()
                )
                alerts.append(("warn", "◆",
                    f"{len(at_risk)} at-risk regulars",
                    f"Customers with 3+ orders in the prior 60 days "
                    f"who haven't ordered in the last 30:<br>{names_html}"))

        # 5) Profitability — overall margin compression vs baseline
        if "margin" in df_curr.columns:
            curr_rev_a = float(df_curr["amount_total"].sum())
            curr_prof_a = float(df_curr["margin"].sum())
            curr_gm_a = (curr_prof_a / curr_rev_a * 100) if curr_rev_a else 0
            # Baseline margin: same period spans, prior 4 cycles
            span_a = (curr_end - curr_start).days + 1
            prior_revs_a, prior_profs_a = [], []
            for i in range(1, 5):
                ps = curr_start - timedelta(days=span_a * i)
                pe = ps + timedelta(days=span_a - 1)
                d_pri = df[(df["day"] >= ps) & (df["day"] <= pe)]
                if not d_pri.empty:
                    prior_revs_a.append(float(d_pri["amount_total"].sum()))
                    prior_profs_a.append(float(d_pri["margin"].sum()))
            base_rev = sum(prior_revs_a)
            base_prof = sum(prior_profs_a)
            base_gm = (base_prof / base_rev * 100) if base_rev else 0
            if base_gm > 0:
                ppt_diff = curr_gm_a - base_gm
                if ppt_diff <= -3:
                    alerts.append(("bad", "▼",
                        "Margin compression",
                        f"Gross margin of <b>{curr_gm_a:.1f}%</b> is "
                        f"<b>{abs(ppt_diff):.1f}ppt below</b> the 4-period baseline "
                        f"of {base_gm:.1f}%. "
                        f"Profit dollars: {fmt_money(curr_prof_a, CURRENCY, compact=True)} "
                        f"on revenue of {fmt_money(curr_rev_a, CURRENCY, compact=True)}."))
                elif ppt_diff >= 3:
                    alerts.append(("good", "▲",
                        "Margin expansion",
                        f"Gross margin of <b>{curr_gm_a:.1f}%</b> is "
                        f"<b>{ppt_diff:.1f}ppt above</b> the 4-period baseline "
                        f"of {base_gm:.1f}%. "
                        f"Period profit: {fmt_money(curr_prof_a, CURRENCY, compact=True)}."))

        # 6) Loss-making orders (negative margin)
        if "margin" in df_curr.columns:
            losses = df_curr[df_curr["margin"] < 0]
            if not losses.empty:
                total_loss = float(losses["margin"].sum())
                top_losers = (losses.groupby("customer")["margin"].sum()
                              .sort_values().head(5))
                names_html_l = "<br>".join(
                    f"&nbsp;&nbsp;• {c} — loss of {fmt_money(abs(v), CURRENCY, compact=True)}"
                    for c, v in top_losers.items()
                )
                alerts.append(("bad", "✖",
                    f"{len(losses)} loss-making orders",
                    f"Combined negative margin of "
                    f"<b>{fmt_money(abs(total_loss), CURRENCY, compact=True)}</b> "
                    f"this period. Worst customers:<br>{names_html_l}"))

        # 7) Channel margin anomalies — channels whose margin diverges sharply
        if "margin" in df_curr.columns:
            ch_curr_p = (df_curr.groupby("channel")
                         .agg(rev=("amount_total", "sum"),
                              prof=("margin", "sum")))
            ch_curr_p["gm"] = ch_curr_p.apply(
                lambda r: r["prof"] / r["rev"] * 100 if r["rev"] else 0, axis=1
            )
            for ch_ in ch_curr_p.index:
                # Baseline GM for this channel from prior 4 cycles
                base_revs, base_profs = [], []
                for i in range(1, 5):
                    ps = curr_start - timedelta(days=span_a * i)
                    pe = ps + timedelta(days=span_a - 1)
                    d_p = df[(df["day"] >= ps) & (df["day"] <= pe) & (df["channel"] == ch_)]
                    if not d_p.empty:
                        base_revs.append(float(d_p["amount_total"].sum()))
                        base_profs.append(float(d_p["margin"].sum()))
                if base_revs and sum(base_revs) > 0:
                    bgm = sum(base_profs) / sum(base_revs) * 100
                    cgm = float(ch_curr_p.loc[ch_, "gm"])
                    diff = cgm - bgm
                    if diff <= -5:
                        alerts.append(("bad", "▼",
                            f"{ch_} margin slipping",
                            f"Gross margin of <b>{cgm:.1f}%</b> is "
                            f"<b>{abs(diff):.1f}ppt below</b> "
                            f"its 4-period baseline of {bgm:.1f}%."))
                    elif diff >= 5:
                        alerts.append(("good", "▲",
                            f"{ch_} margin improving",
                            f"Gross margin of <b>{cgm:.1f}%</b> is "
                            f"<b>{diff:.1f}ppt above</b> "
                            f"its 4-period baseline of {bgm:.1f}%."))

        # 8) High-revenue / low-margin customers (worth re-pricing)
        if "margin" in df_curr.columns and curr_rev > 0:
            cust_p = (df_curr.groupby("customer")
                      .agg(rev=("amount_total", "sum"),
                           prof=("margin", "sum")))
            cust_p["gm"] = cust_p.apply(
                lambda r: r["prof"] / r["rev"] * 100 if r["rev"] else 0, axis=1
            )
            # Top 10% of customers by revenue (only if there's a meaningful base)
            if len(cust_p) >= 10:
                rev_p90 = cust_p["rev"].quantile(0.9)
                bigs = cust_p[cust_p["rev"] >= rev_p90]
                # Among those, anyone with sub-15% gross margin
                low_gm = bigs[bigs["gm"] < 15].sort_values("rev", ascending=False).head(5)
                if not low_gm.empty:
                    rows_html = "<br>".join(
                        f"&nbsp;&nbsp;• {c} — {fmt_money(r['rev'], CURRENCY, compact=True)} rev "
                        f"at {r['gm']:.1f}% margin"
                        for c, r in low_gm.iterrows()
                    )
                    alerts.append(("warn", "◆",
                        "High revenue, thin margin",
                        f"Top-decile customers whose gross margin is below 15% — "
                        f"candidates for re-pricing or cost review:<br>{rows_html}"))

        # 9) Best day callout
        by_day = df_curr.groupby("day")["amount_total"].sum()
        if len(by_day) > 1:
            best_day = by_day.idxmax()
            best_v = by_day.max()
            avg_v = by_day.mean()
            if avg_v and best_v / avg_v >= 1.5:
                alerts.append(("good", "★",
                    f"Standout day · {best_day.strftime('%a %d %b')}",
                    f"<b>{fmt_money(best_v, CURRENCY, compact=True)}</b> — "
                    f"<b>{best_v/avg_v:.1f}×</b> the period's daily average."))

    # ---------- Render alerts ----------
    if not alerts:
        st.markdown(
            "<div class='brief-card'><p class='brief-callout brief-good'>"
            "No anomalies detected for this period — performance is within "
            "normal ranges across customers and channels."
            "</p></div>",
            unsafe_allow_html=True,
        )
    else:
        # Group by severity
        severity_order = {"bad": 0, "warn": 1, "good": 2}
        alerts.sort(key=lambda a: severity_order.get(a[0], 99))
        cards_html = ""
        for severity, icon, title, body in alerts:
            color, ic_bg = {
                "bad":  ("#F87171", "rgba(248,113,113,0.10)"),
                "warn": ("#F5B544", "rgba(245,181,68,0.10)"),
                "good": ("#22C55E", "rgba(34,197,94,0.10)"),
            }.get(severity, ("#A1A1AA", "rgba(161,161,170,0.10)"))
            cards_html += (
                f"<div class='alert-card' style='border-left:3px solid {color}'>"
                f"<div class='alert-ic' style='color:{color};background:{ic_bg}'>{icon}</div>"
                f"<div class='alert-body'>"
                f"<div class='alert-title'>{title}</div>"
                f"<div class='alert-tx'>{body}</div>"
                f"</div></div>"
            )
        st.markdown(f"<div class='alert-grid'>{cards_html}</div>",
                    unsafe_allow_html=True)


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


# -------- Cohorts & Retention --------
with tab_cohorts:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='sec'><h3>Customer cohorts &amp; retention</h3>"
        "<div class='sec-sub'>Each row is a customer's first-purchase month; "
        "columns show the % that came back N months later</div></div>",
        unsafe_allow_html=True,
    )

    if df.empty:
        st.info("No customer data available.")
    else:
        # Compute first-purchase month per customer
        first_order = df.groupby("customer")["dt_local"].min().reset_index()
        first_order["cohort"] = first_order["dt_local"].dt.to_period("M")
        # All orders, tagged with their customer's cohort
        co = df.merge(first_order[["customer", "cohort"]], on="customer", how="left")
        co["order_period"] = co["dt_local"].dt.to_period("M")
        co["months_offset"] = (
            (co["order_period"] - co["cohort"]).apply(lambda p: p.n)
        )

        # Build retention matrix (% of cohort retained)
        cohort_users = (co.groupby(["cohort", "months_offset"])["customer"]
                        .nunique().reset_index())
        cohort_size = (cohort_users[cohort_users["months_offset"] == 0]
                       .set_index("cohort")["customer"])
        cohort_users["retention"] = cohort_users.apply(
            lambda r: r["customer"] / cohort_size[r["cohort"]] * 100
            if r["cohort"] in cohort_size and cohort_size[r["cohort"]] else 0,
            axis=1,
        )
        matrix = (cohort_users
                  .pivot(index="cohort", columns="months_offset", values="retention")
                  .sort_index())

        # KPIs about retention
        avg_repeat = float(matrix.iloc[:, 1:].stack().mean()) if matrix.shape[1] > 1 else 0
        m1_repeat = float(matrix[1].mean()) if 1 in matrix.columns else 0
        total_customers = int(cohort_size.sum())
        # New vs returning revenue in current scope
        if not df_curr.empty:
            df_c = df_curr.merge(first_order[["customer", "cohort"]],
                                 on="customer", how="left")
            df_c["order_period"] = df_c["dt_local"].dt.to_period("M")
            df_c["is_new"] = df_c["order_period"] == df_c["cohort"]
            new_rev = float(df_c[df_c["is_new"]]["amount_total"].sum())
            ret_rev = float(df_c[~df_c["is_new"]]["amount_total"].sum())
        else:
            new_rev = ret_rev = 0
        new_pct = (new_rev / (new_rev + ret_rev) * 100) if (new_rev + ret_rev) else 0

        kpi_html = "<div class='kpi-grid'>"
        kpi_html += kpi_card(
            "Total customers tracked",
            f"{total_customers:,}",
            f"Across {len(cohort_size)} acquisition cohorts",
            "",
        )
        kpi_html += kpi_card(
            "Month-1 repeat rate",
            f"{m1_repeat:.1f}%",
            "Average % of customers who came back the very next month",
            "",
        )
        kpi_html += kpi_card(
            "Avg retention (M1+)",
            f"{avg_repeat:.1f}%",
            "Mean retention across all months after acquisition",
            "",
        )
        kpi_html += kpi_card(
            f"New vs returning · {scope_label}",
            f"{new_pct:.0f}% new",
            f"<b>{fmt_money(new_rev, CURRENCY, compact=True)}</b> from new · "
            f"<b>{fmt_money(ret_rev, CURRENCY, compact=True)}</b> from returning",
            "",
        )
        kpi_html += "</div>"
        st.markdown(kpi_html, unsafe_allow_html=True)

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

        # ---------- Cohort heatmap ----------
        st.markdown("<div class='sec'><h3>Retention heatmap</h3>"
                    "<div class='sec-sub'>Cell = % of that cohort still active "
                    "in that month after first purchase</div></div>",
                    unsafe_allow_html=True)
        if matrix.shape[0] > 0 and matrix.shape[1] > 1:
            # Limit to last 12 cohorts and first 12 month offsets to keep it readable
            mat = matrix.iloc[-12:, :12]
            text_z = [[(f"{v:.0f}%" if pd.notna(v) and v > 0 else "")
                       for v in row] for row in mat.values]
            fig = go.Figure(go.Heatmap(
                z=mat.values,
                x=[f"M+{c}" for c in mat.columns],
                y=[str(idx) for idx in mat.index],
                colorscale=[[0, "#0A0A0B"], [0.5, "#0E5A4A"], [1, "#19E3B6"]],
                text=text_z,
                texttemplate="%{text}",
                textfont=dict(size=10, color="#F4F4F5"),
                hovertemplate="Cohort %{y}<br>Month %{x}<br>%{z:.1f}%<extra></extra>",
                showscale=False,
                zmin=0, zmax=100,
            ))
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(style_fig(fig, height=420, show_legend=False),
                            use_container_width=True)
        else:
            st.info("Not enough multi-month history yet to build cohort retention.")

        # ---------- New vs Returning revenue over time ----------
        st.markdown("<div class='sec' style='margin-top:14px'>"
                    "<h3>New vs returning revenue · monthly</h3></div>",
                    unsafe_allow_html=True)
        df_all = df.merge(first_order[["customer", "cohort"]],
                          on="customer", how="left")
        df_all["order_period"] = df_all["dt_local"].dt.to_period("M")
        df_all["is_new"] = df_all["order_period"] == df_all["cohort"]
        df_all["month_label"] = df_all["order_period"].astype(str)
        nvr = (df_all.groupby(["month_label", "is_new"])["amount_total"]
               .sum().unstack(fill_value=0).reset_index())
        if True in nvr.columns:
            nvr = nvr.rename(columns={True: "new", False: "returning"})
        else:
            nvr["new"] = 0
        if "returning" not in nvr.columns:
            nvr["returning"] = 0
        nvr = nvr.sort_values("month_label").tail(18)

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=nvr["month_label"], y=nvr["new"], name="New",
            marker=dict(color="#19E3B6", line=dict(width=0)),
            text=nvr["new"], texttemplate="%{text:,.0f}",
            textposition="inside", textfont=dict(color="#07221C", size=10),
            hovertemplate="<b>%{x}</b><br>New: %{y:,.0f} " + CURRENCY + "<extra></extra>",
        ))
        fig.add_trace(go.Bar(
            x=nvr["month_label"], y=nvr["returning"], name="Returning",
            marker=dict(color="#52525B", line=dict(width=0)),
            text=nvr["returning"], texttemplate="%{text:,.0f}",
            textposition="inside", textfont=dict(color="#F4F4F5", size=10),
            hovertemplate="<b>%{x}</b><br>Returning: %{y:,.0f} " + CURRENCY + "<extra></extra>",
        ))
        fig.update_layout(barmode="stack")
        st.plotly_chart(style_fig(fig, height=320), use_container_width=True)

        # ---------- Customer LTV distribution ----------
        st.markdown("<div class='sec' style='margin-top:14px'>"
                    "<h3>Customer revenue distribution</h3>"
                    "<div class='sec-sub'>How concentrated is revenue across customers?</div></div>",
                    unsafe_allow_html=True)
        ltv = df.groupby("customer")["amount_total"].sum().sort_values(ascending=False)
        if not ltv.empty:
            ltv_med = float(ltv.median())
            ltv_p90 = float(ltv.quantile(0.9))
            ltv_p99 = float(ltv.quantile(0.99))
            stat_html = "<div class='kpi-grid'>"
            stat_html += kpi_card("Median customer LTV",
                                  fmt_money(ltv_med, CURRENCY), "", "")
            stat_html += kpi_card("90th percentile LTV",
                                  fmt_money(ltv_p90, CURRENCY),
                                  "Top 10% of customers spend at least this much", "")
            stat_html += kpi_card("99th percentile LTV",
                                  fmt_money(ltv_p99, CURRENCY),
                                  "Top 1% threshold", "")
            stat_html += "</div>"
            st.markdown(stat_html, unsafe_allow_html=True)

            # Histogram
            fig = go.Figure(go.Histogram(
                x=ltv.values, nbinsx=40,
                marker=dict(color="#19E3B6", line=dict(width=0)),
                hovertemplate="Range: %{x}<br>Customers: %{y}<extra></extra>",
            ))
            fig.update_layout(bargap=0.05)
            fig.update_xaxes(title=f"Customer lifetime revenue ({CURRENCY})")
            fig.update_yaxes(title="Customers")
            st.plotly_chart(style_fig(fig, height=300, show_legend=False),
                            use_container_width=True)


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


# -------- Geography --------
with tab_geo:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='sec'><h3>Customer geography</h3>"
        f"<div class='sec-sub'>{scope_label} · "
        "city-level mapping (Odoo addresses → known coordinates)</div></div>",
        unsafe_allow_html=True,
    )
    if df_curr.empty:
        st.info("No data in selected window.")
    else:
        # Helper that handles NaN / None / non-numeric partner_id values
        def _safe_pid(pid):
            if pid is None or pd.isna(pid):
                return None
            try:
                return int(pid)
            except (TypeError, ValueError):
                return None

        def _lookup(pid, key):
            ipid = _safe_pid(pid)
            if ipid is None:
                return None
            return addr_map.get(ipid, {}).get(key)

        # Pull partner addresses for everyone in the current slice
        unique_partners = tuple(sorted({
            ipid for p in df_curr["partner_id"].tolist()
            if (ipid := _safe_pid(p)) is not None
        }))
        with st.spinner("Resolving customer addresses..."):
            addr_map = fetch_partner_addresses(unique_partners)

        # Build per-order frame with city/coords
        geo_df = df_curr.copy()
        geo_df["city_raw"] = geo_df["partner_id"].map(lambda p: _lookup(p, "city"))
        geo_df["country"]  = geo_df["partner_id"].map(lambda p: _lookup(p, "country"))
        geo_df["coords"]   = geo_df["city_raw"].map(city_to_coords)
        # Prefer real Odoo coords if ever populated
        geo_df["lat_partner"] = geo_df["partner_id"].map(lambda p: _lookup(p, "lat"))
        geo_df["lon_partner"] = geo_df["partner_id"].map(lambda p: _lookup(p, "lon"))
        # If partner_lat / lon are populated, use them; else fall back to city
        def _resolved_coords(row):
            if row["lat_partner"] and row["lon_partner"]:
                return (row["lat_partner"], row["lon_partner"])
            return row["coords"]
        geo_df["resolved"] = geo_df.apply(_resolved_coords, axis=1)
        geo_df["lat"] = geo_df["resolved"].map(lambda c: c[0] if c else None)
        geo_df["lon"] = geo_df["resolved"].map(lambda c: c[1] if c else None)

        mappable = geo_df[geo_df["lat"].notna() & geo_df["lon"].notna()].copy()
        unmapped_rows = geo_df[geo_df["lat"].isna()]
        unmapped_rev = float(unmapped_rows["amount_total"].sum())
        unmapped_orders = len(unmapped_rows)

        # Coverage stats
        total_rev = float(geo_df["amount_total"].sum())
        mapped_rev = float(mappable["amount_total"].sum()) if not mappable.empty else 0
        cov_pct = (mapped_rev / total_rev * 100) if total_rev else 0

        cv1, cv2, cv3, cv4 = st.columns(4)
        cv1.markdown(kpi_card(
            "Mapped revenue",
            fmt_money(mapped_rev, CURRENCY, compact=True),
            f"<span style='color:#19E3B6'>{cov_pct:.1f}%</span> of period revenue",
        ), unsafe_allow_html=True)
        cv2.markdown(kpi_card(
            "Mapped orders",
            f"{len(mappable):,}",
            f"<span style='color:#71717A'>of {len(geo_df):,} total</span>",
        ), unsafe_allow_html=True)
        cv3.markdown(kpi_card(
            "Unmapped revenue",
            fmt_money(unmapped_rev, CURRENCY, compact=True),
            f"<span style='color:#71717A'>{unmapped_orders:,} orders without city</span>",
        ), unsafe_allow_html=True)
        cv4.markdown(kpi_card(
            "Cities reached",
            f"{mappable.groupby(['lat','lon']).ngroups if not mappable.empty else 0}",
            "<span style='color:#71717A'>distinct locations</span>",
        ), unsafe_allow_html=True)

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        if mappable.empty:
            st.warning(
                "No customer in this period has a recognised city. "
                "Either the city field is empty in Odoo, or the city name "
                "isn't in our coordinate table yet."
            )
        else:
            # Aggregate by (lat, lon, city_raw)
            city_agg = (mappable.groupby(["lat", "lon", "city_raw"])
                        .agg(revenue=("amount_total", "sum"),
                             orders=("amount_total", "count"),
                             customers=("customer", pd.Series.nunique))
                        .reset_index()
                        .sort_values("revenue", ascending=False))

            # Bubble size — square-root scaling so small cities are still visible
            max_rev = city_agg["revenue"].max() or 1
            city_agg["bubble"] = (city_agg["revenue"] / max_rev) ** 0.5 * 60 + 8

            # ---- Professional dark map (Carto Dark Matter, no token needed) ----
            hover_text = [
                f"<b>{c}</b><br>"
                f"Revenue: {fmt_money(r, CURRENCY, compact=True)}<br>"
                f"Orders: {o:,}<br>"
                f"Customers: {cu:,}"
                for c, r, o, cu in zip(
                    city_agg["city_raw"], city_agg["revenue"],
                    city_agg["orders"], city_agg["customers"])
            ]

            # Smart zoom and centre based on the spread of cities
            lat_min, lat_max = float(city_agg["lat"].min()), float(city_agg["lat"].max())
            lon_min, lon_max = float(city_agg["lon"].min()), float(city_agg["lon"].max())
            span = max(lat_max - lat_min, lon_max - lon_min)
            if span < 0.5:
                zoom = 8.5
            elif span < 2:
                zoom = 7.2
            elif span < 5:
                zoom = 6.4
            elif span < 10:
                zoom = 4.8
            else:
                zoom = 3.2
            center_lat = (lat_max + lat_min) / 2
            center_lon = (lon_max + lon_min) / 2

            # Two-layer effect: a soft outer halo behind the bright core marker
            fig = go.Figure()
            # Halo layer
            fig.add_trace(go.Scattermapbox(
                lon=city_agg["lon"], lat=city_agg["lat"],
                mode="markers",
                marker=dict(
                    size=city_agg["bubble"] * 1.7,
                    color="#19E3B6",
                    opacity=0.18,
                    allowoverlap=True,
                ),
                hoverinfo="skip",
                showlegend=False,
            ))
            # Core marker layer
            fig.add_trace(go.Scattermapbox(
                lon=city_agg["lon"], lat=city_agg["lat"],
                mode="markers+text",
                marker=dict(
                    size=city_agg["bubble"],
                    color=city_agg["revenue"],
                    colorscale=[
                        [0.0, "#0E5A4A"],
                        [0.5, "#19E3B6"],
                        [1.0, "#7FFFD4"],
                    ],
                    opacity=0.92,
                    allowoverlap=True,
                ),
                text=city_agg["city_raw"],
                textposition="top right",
                textfont=dict(
                    family="Inter, sans-serif",
                    size=11,
                    color="#F4F4F5",
                ),
                customdata=hover_text,
                hovertemplate="%{customdata}<extra></extra>",
                showlegend=False,
            ))

            fig.update_layout(
                mapbox=dict(
                    style="carto-darkmatter",
                    center=dict(lat=center_lat, lon=center_lon),
                    zoom=zoom,
                ),
                paper_bgcolor=PALETTE["surface"],
                plot_bgcolor=PALETTE["surface"],
                margin=dict(l=0, r=0, t=0, b=0),
                height=560,
                font=dict(family="Inter, sans-serif", color=PALETTE["text_dim"]),
                hoverlabel=dict(
                    bgcolor=PALETTE["surface2"],
                    bordercolor=PALETTE["border_lt"],
                    font_color=PALETTE["text"],
                    font_family="Inter",
                    font_size=12,
                ),
            )
            st.plotly_chart(
                fig, use_container_width=True,
                config={"displayModeBar": False, "scrollZoom": True},
            )

            # Below the map: bar chart + table
            g1, g2 = st.columns([3, 2])
            with g1:
                st.markdown("<div class='sec'><h3>Revenue by city</h3></div>",
                            unsafe_allow_html=True)
                top_cities = city_agg.head(15)
                bar = go.Figure(go.Bar(
                    x=top_cities["revenue"], y=top_cities["city_raw"],
                    orientation="h",
                    marker=dict(
                        color=top_cities["revenue"],
                        colorscale=[[0, "#0E5A4A"], [1, "#19E3B6"]],
                        line=dict(width=0),
                    ),
                    text=top_cities["revenue"],
                    texttemplate="%{text:,.0f}",
                    textposition="outside",
                    textfont=dict(color=PALETTE["text_dim"], size=10),
                    cliponaxis=False,
                    hovertemplate="<b>%{y}</b><br>%{x:,.0f} " + CURRENCY +
                                  "<extra></extra>",
                ))
                bar.update_yaxes(autorange="reversed")
                st.plotly_chart(style_fig(bar, height=420, show_legend=False),
                                use_container_width=True)
            with g2:
                st.markdown("<div class='sec'><h3>City ranking</h3></div>",
                            unsafe_allow_html=True)
                tbl = city_agg[["city_raw", "revenue", "orders", "customers"]].copy()
                tbl.columns = ["City", f"Revenue ({CURRENCY})", "Orders", "Customers"]
                st.dataframe(
                    tbl, use_container_width=True, hide_index=True, height=420,
                    column_config={
                        f"Revenue ({CURRENCY})":
                            st.column_config.NumberColumn(format="%,.0f"),
                        "Orders": st.column_config.NumberColumn(format="%,d"),
                        "Customers": st.column_config.NumberColumn(format="%,d"),
                    },
                )

            if unmapped_rev > 0:
                st.caption(
                    f"<span style='color:#71717A;font-size:11px'>"
                    f"{fmt_money(unmapped_rev, CURRENCY, compact=True)} of revenue "
                    f"({unmapped_orders:,} orders) couldn't be placed on the map "
                    "— customer either has no city in Odoo or a city name not "
                    "yet in our coordinate table. To improve coverage, fill in "
                    "the city field on those Odoo contacts."
                    "</span>",
                    unsafe_allow_html=True,
                )


# -------- Period Comparator --------
with tab_compare:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='sec'><h3>Period comparator</h3>"
        "<div class='sec-sub'>Pick any two date ranges and compare them side-by-side</div></div>",
        unsafe_allow_html=True,
    )

    cmp_col1, cmp_col2 = st.columns(2)
    with cmp_col1:
        st.markdown(
            "<div style='color:#19E3B6;font-size:11px;font-weight:700;"
            "letter-spacing:0.18em;margin-bottom:6px'>PERIOD A</div>",
            unsafe_allow_html=True,
        )
        a_range = st.date_input(
            "A range",
            value=(today_local.replace(day=1), today_local),
            label_visibility="collapsed", key="cmp_a",
        )
    with cmp_col2:
        st.markdown(
            "<div style='color:#A78BFA;font-size:11px;font-weight:700;"
            "letter-spacing:0.18em;margin-bottom:6px'>PERIOD B</div>",
            unsafe_allow_html=True,
        )
        # Default B = same period last month
        try:
            b_default_start = (today_local.replace(day=1) - timedelta(days=1)).replace(day=1)
            b_default_end = today_local.replace(day=1) - timedelta(days=1)
        except Exception:
            b_default_start = today_local - timedelta(days=60)
            b_default_end = today_local - timedelta(days=30)
        b_range = st.date_input(
            "B range",
            value=(b_default_start, b_default_end),
            label_visibility="collapsed", key="cmp_b",
        )

    def _resolve_range(r):
        if isinstance(r, tuple) and len(r) == 2:
            return r
        return (r if not isinstance(r, tuple) else r[0]), today_local

    a_start, a_end = _resolve_range(a_range)
    b_start, b_end = _resolve_range(b_range)

    df_a = slice_df(df, a_start, a_end)
    df_b = slice_df(df, b_start, b_end)

    a_rev = float(df_a["amount_total"].sum()) if not df_a.empty else 0
    b_rev = float(df_b["amount_total"].sum()) if not df_b.empty else 0
    a_orders = len(df_a)
    b_orders = len(df_b)
    a_aov = a_rev / a_orders if a_orders else 0
    b_aov = b_rev / b_orders if b_orders else 0
    a_cust = df_a["customer"].nunique() if not df_a.empty else 0
    b_cust = df_b["customer"].nunique() if not df_b.empty else 0

    def _delta_block(a_v, b_v, currency=False):
        if not b_v:
            return "<span style='color:#71717A'>—</span>"
        pct = (a_v - b_v) / b_v * 100
        cls = "kpi-delta-up" if pct >= 0 else "kpi-delta-dn"
        arrow = "▲" if pct >= 0 else "▼"
        return f"<span class='{cls}'>{arrow} {abs(pct):.1f}%</span>"

    # KPI grid: A | B | Δ
    rows = [
        ("Revenue", fmt_money(a_rev, CURRENCY, compact=True),
         fmt_money(b_rev, CURRENCY, compact=True), _delta_block(a_rev, b_rev)),
        ("Orders", f"{a_orders:,}", f"{b_orders:,}",
         _delta_block(a_orders, b_orders)),
        ("AOV", fmt_money(a_aov, CURRENCY), fmt_money(b_aov, CURRENCY),
         _delta_block(a_aov, b_aov)),
        ("Customers", f"{a_cust:,}", f"{b_cust:,}",
         _delta_block(a_cust, b_cust)),
    ]
    table_html = (
        "<div style='margin-top:10px;border:1px solid #23232B;border-radius:14px;"
        "overflow:hidden'>"
        "<div style='display:grid;grid-template-columns:1.4fr 1fr 1fr 1fr;"
        "background:#16161B;padding:14px 18px;font-size:11px;color:#71717A;"
        "font-weight:700;text-transform:uppercase;letter-spacing:0.12em;"
        "border-bottom:1px solid #23232B'>"
        "<div>Metric</div>"
        f"<div style='color:#19E3B6'>A · {a_start.strftime('%d %b')} → {a_end.strftime('%d %b')}</div>"
        f"<div style='color:#A78BFA'>B · {b_start.strftime('%d %b')} → {b_end.strftime('%d %b')}</div>"
        "<div>A vs B</div>"
        "</div>"
    )
    for label, av, bv, dv in rows:
        table_html += (
            "<div style='display:grid;grid-template-columns:1.4fr 1fr 1fr 1fr;"
            "padding:16px 18px;border-bottom:1px solid #1F1F26;align-items:center'>"
            f"<div style='color:#A1A1AA;font-size:12.5px;font-weight:600'>{label}</div>"
            f"<div style='color:#F4F4F5;font-size:18px;font-weight:700;letter-spacing:-0.01em'>{av}</div>"
            f"<div style='color:#F4F4F5;font-size:18px;font-weight:700;letter-spacing:-0.01em'>{bv}</div>"
            f"<div style='font-size:14px;font-weight:600'>{dv}</div>"
            "</div>"
        )
    table_html += "</div>"
    st.markdown(table_html, unsafe_allow_html=True)

    # Channel breakdown side-by-side
    st.markdown("<div class='sec' style='margin-top:18px'>"
                "<h3>Channel breakdown</h3></div>",
                unsafe_allow_html=True)
    if df_a.empty and df_b.empty:
        st.info("No data in either selected range.")
    else:
        ch_a = df_a.groupby("channel")["amount_total"].sum() if not df_a.empty else pd.Series(dtype=float)
        ch_b = df_b.groupby("channel")["amount_total"].sum() if not df_b.empty else pd.Series(dtype=float)
        all_ch = sorted(set(list(ch_a.index) + list(ch_b.index)),
                        key=lambda c: -max(ch_a.get(c, 0), ch_b.get(c, 0)))
        a_vals = [ch_a.get(c, 0) for c in all_ch]
        b_vals = [ch_b.get(c, 0) for c in all_ch]
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=all_ch, y=a_vals, name="A",
            marker=dict(color="#19E3B6", line=dict(width=0)),
            text=a_vals, texttemplate="%{text:,.0f}",
            textposition="outside",
            textfont=dict(color="#19E3B6", size=10),
            cliponaxis=False,
            hovertemplate="A · %{x}<br>%{y:,.0f} " + CURRENCY + "<extra></extra>",
        ))
        fig.add_trace(go.Bar(
            x=all_ch, y=b_vals, name="B",
            marker=dict(color="#A78BFA", line=dict(width=0)),
            text=b_vals, texttemplate="%{text:,.0f}",
            textposition="outside",
            textfont=dict(color="#A78BFA", size=10),
            cliponaxis=False,
            hovertemplate="B · %{x}<br>%{y:,.0f} " + CURRENCY + "<extra></extra>",
        ))
        fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.08)
        st.plotly_chart(style_fig(fig, height=380), use_container_width=True)


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
