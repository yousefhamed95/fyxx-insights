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
import math
import re
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

/* Hero scope label — solid neon green to match the rest of the accents */
.hero-accent {
    color: #19E3B6 !important;
    background: none !important;
    -webkit-background-clip: initial !important;
    -webkit-text-fill-color: #19E3B6 !important;
    background-clip: initial !important;
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

/* DataFrames — refined wrapper styling */
[data-testid="stDataFrame"] {
    border-radius: 14px;
    border: 1px solid #23232B;
    overflow: hidden;
    background: linear-gradient(160deg, #131318 0%, #0E0E13 100%);
    box-shadow: 0 4px 16px -8px rgba(0, 0, 0, 0.35);
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
[data-testid="stDataFrame"]:hover {
    border-color: #2D2D38;
    box-shadow: 0 6px 22px -8px rgba(0, 0, 0, 0.40);
}
/* Soft heading above tables (when added via .dt-head) */
.dt-head {
    display: flex; justify-content: space-between; align-items: baseline;
    padding: 0 4px 8px 4px;
    font-size: 11px; color: #71717A;
    letter-spacing: 0.10em; text-transform: uppercase; font-weight: 600;
}
.dt-head b { color: #E4E4E7; font-weight: 700; }
.dt-head .count {
    color: #52525B;
    font-variant-numeric: tabular-nums;
    font-size: 10.5px;
}

/* ===== Leaderboard component (custom HTML for top-N tables) ===== */
.lb-card {
    background: linear-gradient(160deg, #131318 0%, #0E0E13 100%);
    border: 1px solid #23232B;
    border-radius: 14px;
    overflow: hidden;
    box-shadow: 0 4px 16px -8px rgba(0,0,0,0.35);
}
.lb-row {
    display: grid;
    grid-template-columns: 30px 1fr auto;
    gap: 14px;
    align-items: center;
    padding: 11px 16px;
    border-bottom: 1px solid #1A1A20;
    transition: background 0.15s ease;
}
.lb-row:last-child { border-bottom: none; }
.lb-row:hover { background: rgba(25, 227, 182, 0.04); }
.lb-rank {
    width: 26px; height: 26px;
    border-radius: 7px;
    display: flex; align-items: center; justify-content: center;
    font-size: 11.5px; font-weight: 700;
    background: rgba(255,255,255,0.03);
    color: #71717A;
    border: 1px solid #23232B;
    font-variant-numeric: tabular-nums;
    flex-shrink: 0;
}
.lb-rank.lb-gold {
    background: linear-gradient(135deg, rgba(245,181,68,0.20), rgba(245,181,68,0.06));
    color: #FCD34D;
    border-color: rgba(245, 181, 68, 0.40);
    box-shadow: 0 0 0 1px rgba(245,181,68,0.10) inset;
}
.lb-rank.lb-silver {
    background: linear-gradient(135deg, rgba(229,231,235,0.14), rgba(229,231,235,0.04));
    color: #E5E7EB;
    border-color: rgba(209, 213, 219, 0.30);
}
.lb-rank.lb-bronze {
    background: linear-gradient(135deg, rgba(180,83,9,0.18), rgba(180,83,9,0.04));
    color: #FBA77A;
    border-color: rgba(180, 83, 9, 0.35);
}
.lb-body { min-width: 0; flex: 1; }
.lb-name {
    color: #F4F4F5;
    font-size: 13px;
    font-weight: 500;
    margin-bottom: 5px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    /* Force left-to-right cell flow so Arabic names appear at the LEFT edge of
       the cell, while internal Arabic substrings still read naturally RTL. */
    direction: ltr;
    text-align: left;
    unicode-bidi: embed;
}
.lb-name .lb-sub {
    color: #71717A;
    font-size: 11px;
    font-weight: 400;
    margin-left: 6px;
}
.lb-bar {
    height: 4px;
    background: rgba(255,255,255,0.04);
    border-radius: 2px;
    overflow: hidden;
    position: relative;
}
.lb-bar-fill {
    height: 100%;
    border-radius: 2px;
    background: linear-gradient(90deg, #19E3B6 0%, #38BDF8 100%);
    box-shadow: 0 0 8px rgba(25, 227, 182, 0.30);
    transition: width 0.4s cubic-bezier(0.22, 0.61, 0.36, 1);
}
.lb-value {
    color: #F4F4F5;
    font-size: 13.5px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.01em;
    text-align: right;
    flex-shrink: 0;
}
.lb-value .lb-delta {
    display: block;
    font-size: 10.5px;
    font-weight: 600;
    margin-top: 2px;
}
.lb-value .lb-delta.up { color: #22C55E; }
.lb-value .lb-delta.dn { color: #F87171; }
.lb-empty {
    padding: 24px;
    text-align: center;
    color: #71717A;
    font-size: 12.5px;
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

/* Hero — animated gradient border, single neon-green family only */
.hero {
    display: flex; align-items: center; justify-content: space-between;
    gap: 18px; flex-wrap: wrap;
    padding: 14px 18px;
    margin-bottom: 22px;
    border-radius: 14px;
    border: 1px solid transparent;
    background:
        linear-gradient(160deg, #131318 0%, #0E0E13 100%) padding-box,
        linear-gradient(135deg,
            #0E5A4A, #19E3B6, #5FF5CB, #19E3B6, #0E5A4A) border-box;
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
/* Main KPI strip — force all 6 cards into one row on wide screens */
.kpi-strip-main { grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); }
@media (min-width: 1100px) {
    .kpi-strip-main { grid-template-columns: repeat(6, 1fr) !important; }
}
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

/* ===== Editorial credit line at the very top of the dashboard ===== */
.credit-line {
    text-align: center;
    padding: 10px 0 14px 0;
    margin-bottom: 14px;
    border-bottom: 1px solid #1F1F26;
    color: #A1A1AA;
    font-size: 11.5px;
    font-weight: 500;
    letter-spacing: 0.16em;
    text-transform: uppercase;
}
.credit-line .credit-prefix {
    color: #71717A;
    font-weight: 400;
    margin-right: 4px;
}
.credit-line .credit-body {
    color: #D4D4D8;
    font-weight: 500;
}
.credit-line .credit-sep {
    color: #3F3F46;
    margin: 0 10px;
    font-weight: 400;
}
.credit-line .credit-name {
    color: #E4E4E7;
    font-style: italic;
    font-weight: 600;
    text-transform: none;
    letter-spacing: 0.02em;
}

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
    /* Keep year cards a normal width even when only one is rendered */
    max-width: 360px;
    width: 100%;
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
# Salesperson keywords used to classify sale.order channel
# (must be matched within the Fyxx Operations (B2C) company; anything else falls to Retail)
_ECOM_SALESPERSON_KEYWORDS = ("shopify",)                          # Shopify & Ops.
_B2B_SALESPERSON_KEYWORDS  = ("tareq", "yousef")                   # Tareq Shnoudi / Yousef Mazhareh
_B2C_COMPANY_KEYWORDS      = ("fyxx operations (b2c)", "fyxx operations")
POS_CONFIG_CHANNEL_MAP = {
    3: "TGR",        # Dine-In register (will be line-split: bottles/cigars → Retail)
    2: "Retail",
    5: "Retail",            # Jasmine House → Retail (separate company, rolled up)
    6: "Retail",            # Events (Mobile) → Retail
}
EXCLUDED_POS_CONFIG_IDS = [4]   # Archived (testing POS)

# Stable colour per channel — keeps any chart visually consistent.
# Falls back to CHART_COLORWAY for channels not listed here.
CHANNEL_COLORS = {
    "E-com":      "#19E3B6",  # primary neon
    "Retail":     "#38BDF8",  # sky blue
    "TGR":        "#A78BFA",  # violet (hospitality / dine-in)
    "B2B":        "#F5B544",  # amber/gold (high-AOV wholesale)
    "DF":       "#EC4899",  # rose — Jordanian Duty Free Shops
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
        # Force the on-screen numeric keypad on mobile for the password field.
        from streamlit.components.v1 import html as _pw_components_html
        _pw_components_html(
            """
            <script>
            (function () {
              const apply = () => {
                try {
                  const doc = window.parent.document;
                  doc.querySelectorAll('input[type="password"]').forEach((el) => {
                    el.setAttribute('inputmode', 'numeric');
                    el.setAttribute('pattern', '[0-9]*');
                    el.setAttribute('autocomplete', 'one-time-code');
                  });
                } catch (e) {}
              };
              apply();
              setTimeout(apply, 150);
              setTimeout(apply, 600);
              setTimeout(apply, 1500);
            })();
            </script>
            """,
            height=0,
        )
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


# Customer names that represent internal / company-self transactions.
# Any sale or POS ticket whose customer matches these is excluded from
# EVERY chart, KPI, table, and aggregation in the dashboard.
_EXCLUDED_CUSTOMER_KEYWORDS = (
    "fyxx operations",   # 'Fyxx Operations (B2C)' company self-purchases
    "jt international",  # 'JT INTERNATIONAL ( JORDAN ) LTD.' — exclude entirely
)


# Customer-name patterns that get their own dedicated channel, overriding
# the salesperson/company-based classification. Substring match, case-insensitive.
_CUSTOMER_CHANNEL_OVERRIDES = (
    # Jordanian Duty Free Shops → its own 'DF' channel
    (("jordanian duty free", "duty free shops"), "DF"),
)


def _customer_channel_override(name):
    """Return a channel label if the customer name matches an override
    pattern, otherwise None (so the default channel logic stays in effect)."""
    if not name:
        return None
    low = str(name).strip().lower()
    for keywords, channel in _CUSTOMER_CHANNEL_OVERRIDES:
        if any(k in low for k in keywords):
            return channel
    return None


def _is_internal_customer(name):
    """True if this customer name represents an internal / non-real entry
    that should be excluded from sales aggregations."""
    if not name:
        return False
    low = str(name).strip().lower()
    return any(k in low for k in _EXCLUDED_CUSTOMER_KEYWORDS)


# Bump this when the customer-exclusion rules change so the cache invalidates.
DATA_FILTER_VERSION = 6   # v6 = renamed JDFS channel to DF


def resolve_channel_so(salesperson_name, company_name):
    """Map a sale.order to one of: E-com / Retail / B2B (Green Room is POS-only).

    Rules (set by the user):
      • E-com : salesperson contains 'Shopify' AND company is Fyxx Operations (B2C)
      • B2B   : salesperson contains 'Tareq' or 'Yousef' AND company is Fyxx Operations (B2C)
      • Retail: everything else (other companies, other salespeople)"""
    sp = (salesperson_name or "").strip().lower()
    co = (company_name or "").strip().lower()
    is_b2c = any(k in co for k in _B2C_COMPANY_KEYWORDS)
    if is_b2c:
        if any(k in sp for k in _ECOM_SALESPERSON_KEYWORDS):
            return "E-com"
        if any(k in sp for k in _B2B_SALESPERSON_KEYWORDS):
            return "B2B"
    return "Retail"


def _is_retail_at_green_room(category_path):
    """For a product sold at Green Room (POS Dine-In), decide whether the
    line belongs to RETAIL (take-home bottle / cigar) or stays in GREEN ROOM
    (consumed on-premise: food, cocktails, BTG, dine-in beverages)."""
    if not category_path:
        return False
    p = " " + category_path.lower() + " "
    # On-premise consumption stays in Green Room ↓
    if "(dine-in)" in p or "(di)" in p:
        return False
    if "btg" in p:                         # by-the-glass spirits / wines
        return False
    if "/ food /" in p or p.rstrip().endswith("/ food"):
        return False
    if "/ drinks /" in p:                  # cocktails / mixers / drink-in
        return False
    if "0% beverage" in p:                 # dine-in water / mixers
        return False
    if "/ cocktails" in p:
        return False
    # Take-home retail at Green Room: alcohol bottles, cigars, cigarettes ↓
    if "/ alcohol" in p or "/ tobacco" in p or "cigar" in p:
        return True
    return False


def _split_green_room_to_retail(rows, _ttl_bucket):
    """Walk through `rows` (the output of fetch_orders_window_v5), find every
    POS 'Green Room' row, fetch its lines + product categories, and split
    each order into a Retail row (bottles/cigars) + Green Room row (rest).
    Net / VAT / margin are allocated proportionally."""
    gr_indices = [
        i for i, r in enumerate(rows)
        if r.get("source") == "POS Ticket" and r.get("channel") == "TGR"
    ]
    gr_order_ids = [rows[i].get("order_id") for i in gr_indices if rows[i].get("order_id")]
    if not gr_order_ids:
        return rows

    # 1. Fetch pos.order.line for every Green Room order in the window
    try:
        lines = kw(
            "pos.order.line", "search_read",
            [[["order_id", "in", gr_order_ids]]],
            {"fields": ["order_id", "product_id", "price_subtotal", "margin"],
             "limit": 500000},
        )
    except Exception:
        return rows

    # 2. Fetch product categories (reusing the cached helper)
    prod_ids = tuple(sorted({
        l["product_id"][0] for l in lines if l.get("product_id")
    }))
    cats = fetch_product_categories(prod_ids, _ttl_bucket) if prod_ids else {}

    # 3. Aggregate retail / dine-in totals per Green Room order
    from collections import defaultdict
    splits = defaultdict(lambda: {
        "retail_net": 0.0, "dine_in_net": 0.0,
        "retail_margin": 0.0, "dine_in_margin": 0.0,
    })
    for l in lines:
        if not l.get("order_id") or not l.get("product_id"):
            continue
        oid = l["order_id"][0]
        pid = l["product_id"][0]
        path = cats.get(pid, {}).get("category_path", "") if cats else ""
        net = float(l.get("price_subtotal") or 0)
        mg = float(l.get("margin") or 0)
        if _is_retail_at_green_room(path):
            splits[oid]["retail_net"] += net
            splits[oid]["retail_margin"] += mg
        else:
            splits[oid]["dine_in_net"] += net
            splits[oid]["dine_in_margin"] += mg

    # 4. Rebuild rows: each Green Room order can become 1 or 2 rows
    gr_index_set = set(gr_indices)
    out = []
    for i, r in enumerate(rows):
        if i not in gr_index_set:
            out.append(r)
            continue
        oid = r.get("order_id")
        s = splits.get(oid)
        if not s:
            out.append(r)
            continue
        total = s["retail_net"] + s["dine_in_net"]
        order_vat = float(r.get("vat") or 0)
        if total <= 0:
            out.append(r)
            continue
        if s["retail_net"] > 0:
            ratio = s["retail_net"] / total
            out.append({
                **r,
                "channel": "Retail",
                "amount_total": s["retail_net"],
                "vat": order_vat * ratio,
                "margin": s["retail_margin"],
            })
        if s["dine_in_net"] > 0:
            ratio = s["dine_in_net"] / total
            out.append({
                **r,
                "channel": "TGR",
                "amount_total": s["dine_in_net"],
                "vat": order_vat * ratio,
                "margin": s["dine_in_margin"],
            })
    return out


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
def fetch_orders_window_v5(start_iso, end_iso, _ttl_bucket,
                         _filter_version=DATA_FILTER_VERSION):
    """Fetch sale.order + pos.order in a UTC window. Returns flat row list."""
    so_domain = [
        ["date_order", ">=", start_iso],
        ["date_order", "<=", end_iso],
        ["state", "in", ["sale", "done"]],
    ]
    so_fields = ["name", "partner_id", "user_id", "team_id", "company_id",
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
        partner_id = o["partner_id"][0] if o.get("partner_id") else None
        customer = o["partner_id"][1] if o.get("partner_id") else "—"
        salesperson = o["user_id"][1] if o.get("user_id") else "—"
        company = o["company_id"][1] if o.get("company_id") else None
        rows.append({
            "name": o["name"],
            "order_id": o.get("id"),
            "channel": resolve_channel_so(salesperson, company),
            "customer": customer,
            "partner_id": partner_id,
            "salesperson": salesperson,
            "amount_total": o.get("amount_untaxed", 0.0),
            "vat": float(o.get("amount_tax") or 0),
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
            "order_id": o.get("id"),
            "channel": channel,
            "customer": customer,
            "partner_id": partner_id,
            "salesperson": salesperson,
            "amount_total": net,
            "vat": float(o.get("amount_tax") or 0),
            "margin": float(o.get("margin") or 0),
            "date_order": o["date_order"],
            "state": o["state"],
            "source": "POS Ticket",
        })
    # Global customer filter: exclude internal/self-purchase entries
    # (currently: any customer name containing 'Fyxx Operations')
    rows = [r for r in rows if not _is_internal_customer(r.get("customer"))]
    # Customer-name channel overrides (e.g. Jordanian Duty Free Shops → DF).
    # Done BEFORE the Green Room split so DF orders aren't accidentally
    # split into Retail + TGR rows.
    for r in rows:
        override = _customer_channel_override(r.get("customer"))
        if override:
            r["channel"] = override
    # Line-level reclassification: bottles + cigars sold at Green Room go to Retail
    rows = _split_green_room_to_retail(rows, _ttl_bucket)
    return rows


def load_dataframe(start_date, end_date, tz, ttl_bucket):
    start_utc, end_utc = _date_window_utc(start_date, end_date, tz)
    # Pass DATA_FILTER_VERSION explicitly so it becomes part of the cache key —
    # bumping the constant guarantees a fresh fetch on next render.
    rows = fetch_orders_window_v5(
        start_utc.strftime("%Y-%m-%d %H:%M:%S"),
        end_utc.strftime("%Y-%m-%d %H:%M:%S"),
        ttl_bucket,
        DATA_FILTER_VERSION,
    )
    if not rows:
        return pd.DataFrame(columns=[
            "name", "order_id", "channel", "customer", "partner_id",
            "salesperson", "amount_total", "vat", "margin", "date_order",
            "state", "source", "dt_local", "year", "month", "day",
        ])
    df = pd.DataFrame(rows)
    df["dt_local"] = df["date_order"].apply(lambda s: _to_local_dt(s, tz))
    df["year"] = df["dt_local"].dt.year
    df["month"] = df["dt_local"].dt.month
    df["day"] = df["dt_local"].dt.date
    return df


# =============================================================================
# ONLINE / DRAFT ORDERS BY SHIFT  (dedicated read-only fetch for the Shifts tab)
# =============================================================================
SHIFT_TAB_VERSION = 1   # bump to invalidate the Shifts-tab cache

# Shift boundaries (Asia/Amman local hours), set by the user:
#   Shift 1 "Day"     : 10:00 – 17:00   (10 AM – 5 PM)
#   Shift 2 "Evening" : 17:00 – 01:00   (5 PM – 1 AM, spans midnight)
#   Off-hours         : 01:00 – 10:00   (shown only so daily totals reconcile)
SHIFT_DAY_LABEL = "Day · 10–17"
SHIFT_EVE_LABEL = "Evening · 17–01"
SHIFT_OFF_LABEL = "Off · 01–10"
SHIFT_ORDER = [SHIFT_DAY_LABEL, SHIFT_EVE_LABEL, SHIFT_OFF_LABEL]
SHIFT_COLORS = {
    SHIFT_DAY_LABEL: "#F5B544",   # amber — daytime
    SHIFT_EVE_LABEL: "#A78BFA",   # violet — evening / night
    SHIFT_OFF_LABEL: "#3F3F46",   # muted graphite — off-hours
}


def _shift_of_hour(hour):
    """Bucket an Amman-local hour (0-23) into one of the two shifts, or Off."""
    if 10 <= hour < 17:
        return SHIFT_DAY_LABEL
    if hour >= 17 or hour < 1:        # 17:00–00:59 (wraps past midnight)
        return SHIFT_EVE_LABEL
    return SHIFT_OFF_LABEL


@st.cache_data(ttl=HISTORY_TTL, show_spinner=False)
def fetch_online_draft_orders(start_iso, end_iso, _ttl_bucket,
                              _v=SHIFT_TAB_VERSION):
    """Pull sale.order across ALL states in a UTC window for the Shifts tab.

    Returns flat rows tagged with resolved channel + state so the tab can
    classify each into Online (E-com confirmed), Draft (draft/sent) or
    Cancelled, and bucket it by shift. Strictly read-only."""
    domain = [
        ["date_order", ">=", start_iso],
        ["date_order", "<=", end_iso],
        ["state", "in", ["sale", "done", "draft", "sent", "cancel"]],
    ]
    fields = ["name", "state", "date_order", "user_id", "company_id",
              "partner_id", "amount_untaxed", "amount_tax"]
    try:
        orders = kw("sale.order", "search_read", [domain],
                    {"fields": fields, "limit": 200000,
                     "order": "date_order asc"})
    except Exception:
        orders = []
    rows = []
    for o in orders:
        customer = o["partner_id"][1] if o.get("partner_id") else "—"
        if _is_internal_customer(customer):
            continue
        salesperson = o["user_id"][1] if o.get("user_id") else "—"
        company = o["company_id"][1] if o.get("company_id") else None
        channel = resolve_channel_so(salesperson, company)
        override = _customer_channel_override(customer)
        if override:
            channel = override
        rows.append({
            "name": o["name"],
            "state": o["state"],
            "channel": channel,
            "customer": customer,
            "salesperson": salesperson,
            "net": float(o.get("amount_untaxed") or 0),
            "vat": float(o.get("amount_tax") or 0),
            "date_order": o["date_order"],
        })
    return rows


DELIVERY_TAB_VERSION = 1   # bump to invalidate the delivery cache


@st.cache_data(ttl=HISTORY_TTL, show_spinner=False)
def fetch_delivery_orders(start_iso, end_iso, _ttl_bucket,
                          _v=DELIVERY_TAB_VERSION):
    """Read-only: real 'Delivery Orders' outgoing pickings whose linked sale
    order was placed in the window. Excludes in-store / PoS pickups. Returns
    rows enriched with the order date, resolved channel and the computed
    lead time (order placed → delivery completed, in hours)."""
    try:
        ptypes = kw("stock.picking.type", "search_read",
                    [[["code", "=", "outgoing"]]],
                    {"fields": ["name"], "limit": 100})
    except Exception:
        ptypes = []
    deliv_ids = [p["id"] for p in ptypes if p.get("name") == "Delivery Orders"]
    if not deliv_ids:
        return []
    domain = [
        ["picking_type_id", "in", deliv_ids],
        ["sale_id.date_order", ">=", start_iso],
        ["sale_id.date_order", "<=", end_iso],
    ]
    fields = ["name", "state", "sale_id", "scheduled_date", "date_done",
              "date_deadline", "has_deadline_issue", "carrier_id",
              "carrier_price", "partner_id"]
    try:
        pks = kw("stock.picking", "search_read", [domain],
                 {"fields": fields, "limit": 200000, "order": "id desc"})
    except Exception:
        return []
    # Join the linked sale order (date + salesperson + company for channel)
    sale_ids = list({p["sale_id"][0] for p in pks if p.get("sale_id")})
    so = {}
    for i in range(0, len(sale_ids), 500):
        chunk = sale_ids[i:i + 500]
        try:
            for s in kw("sale.order", "search_read", [[["id", "in", chunk]]],
                        {"fields": ["date_order", "user_id", "company_id",
                                    "partner_id"], "limit": 200000}):
                so[s["id"]] = s
        except Exception:
            pass
    rows = []
    for p in pks:
        sid = p["sale_id"][0] if p.get("sale_id") else None
        s = so.get(sid) if sid else None
        if not s:
            continue
        cust = s["partner_id"][1] if s.get("partner_id") else "—"
        if _is_internal_customer(cust):
            continue
        sp = s["user_id"][1] if s.get("user_id") else "—"
        co = s["company_id"][1] if s.get("company_id") else None
        channel = _customer_channel_override(cust) or resolve_channel_so(sp, co)
        lead = None
        if p.get("date_done") and s.get("date_order"):
            try:
                t0 = datetime.strptime(s["date_order"], "%Y-%m-%d %H:%M:%S")
                t1 = datetime.strptime(p["date_done"], "%Y-%m-%d %H:%M:%S")
                h = (t1 - t0).total_seconds() / 3600
                if 0 <= h < 24 * 120:
                    lead = h
            except Exception:
                pass
        rows.append({
            "name": p["name"],
            "state": p["state"],
            "channel": channel,
            "carrier": (p.get("carrier_id") or [0, "(none)"])[1],
            "carrier_price": float(p.get("carrier_price") or 0),
            "order_date": s.get("date_order"),
            "date_done": p.get("date_done"),
            "lead_hours": lead,
            "late": bool(p.get("has_deadline_issue")),
        })
    return rows


def _ltr(value):
    """Prefix a value with U+200E (LEFT-TO-RIGHT MARK) so any cell that
    contains Arabic (or mixed) text aligns to the LEFT edge in tables
    instead of flipping to right-aligned RTL display."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return value
    return "‎" + str(value)


def _clean_product_name(name):
    """Strip a leading '[code] ' SKU-prefix from an Odoo product display name.
    Example:  '[P-CA-B-1072-S] Carakale | Dead Sea-rious (33cl)'
              -> 'Carakale | Dead Sea-rious (33cl)' """
    if not name:
        return name
    return re.sub(r"^\s*\[[^\]]+\]\s*", "", str(name)).strip()


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
            "product_name": _clean_product_name(l["product_id"][1]),
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
            "product_name": _clean_product_name(l["product_id"][1]),
            "order_id": l["order_id"][0] if l.get("order_id") else None,
            "qty": float(l.get("qty") or 0),
            "revenue": float(l.get("price_subtotal") or 0),
            "margin": float(l.get("margin") or 0),
            "source": "POS Ticket",
        })
    return rows


# Expense / P&L data — pulls aggregated GL balances per expense account.
# Read-only, cached. Used by the P&L tab.
@st.cache_data(ttl=HISTORY_TTL, show_spinner=False)
def fetch_expense_balances(start_date_iso, end_date_iso, _ttl_bucket):
    """Return a list of dicts: one per expense-flavoured account, with the
    debit/credit/balance posted to it within the date range.
    Reads `account.account` + `account.move.line`, posted entries only."""
    try:
        accs = kw("account.account", "search_read", [[]],
                  {"fields": ["id", "name", "code", "account_type"],
                   "limit": 5000})
    except Exception:
        return []
    exp_accs = [a for a in accs
                if "expense" in str(a.get("account_type") or "").lower()]
    if not exp_accs:
        return []
    exp_acc_ids = [a["id"] for a in exp_accs]

    try:
        lines = kw("account.move.line", "search_read",
                   [[["account_id", "in", exp_acc_ids],
                     ["date", ">=", start_date_iso],
                     ["date", "<=", end_date_iso],
                     ["parent_state", "=", "posted"]]],
                   {"fields": ["account_id", "debit", "credit"],
                    "limit": 200000})
    except Exception:
        lines = []

    from collections import defaultdict
    sums = defaultdict(lambda: {"debit": 0.0, "credit": 0.0})
    for l in lines:
        if not l.get("account_id"):
            continue
        aid = l["account_id"][0]
        sums[aid]["debit"] += float(l.get("debit") or 0)
        sums[aid]["credit"] += float(l.get("credit") or 0)

    out = []
    for a in exp_accs:
        b = sums.get(a["id"], {"debit": 0.0, "credit": 0.0})
        out.append({
            "id": a["id"],
            "code": a.get("code") or "",
            "name": a.get("name") or "",
            "type": a.get("account_type") or "",
            "debit": b["debit"],
            "credit": b["credit"],
            "balance": b["debit"] - b["credit"],
        })
    return out


# Product-category lookup — read-only, cached. Returns dict id -> info.
@st.cache_data(ttl=HISTORY_TTL, show_spinner=False)
def fetch_product_categories(product_ids_tuple, _ttl_bucket):
    """Read product.product.categ_id for each id; return id -> dict with
       'subcategory' (leaf), 'group' (top-level), 'category_path' (full)."""
    if not product_ids_tuple:
        return {}
    ids = [int(i) for i in product_ids_tuple if i]
    if not ids:
        return {}
    try:
        rows = kw("product.product", "read", [ids],
                  {"fields": ["id", "categ_id"]})
    except Exception:
        return {}
    out = {}
    for r in rows:
        path = (r["categ_id"][1] if r.get("categ_id") else "") or ""
        if not path:
            out[r["id"]] = {"subcategory": "—", "group": "—",
                            "category_path": "—"}
            continue
        parts = [p.strip() for p in path.split("/") if p.strip()]
        if parts and parts[0].lower() == "all":
            parts = parts[1:]
        if not parts:
            out[r["id"]] = {"subcategory": "—", "group": "—",
                            "category_path": path}
            continue
        # Roll-up rule: any product whose path goes through a "Spirits"
        # parent segment (e.g. "All / Alcohol / Spirits / Whisky" or
        # "... / Spirits / Vodka / Liqueur") is bucketed under a single
        # "Spirits" sub-category instead of the leaf (Whisky, Vodka, ...).
        # Leaf labels that ARE "Spirits" already (like "Spirits (BTG)") stay
        # as-is — only the *child-of-Spirits* leaves get rolled up.
        if any(seg.lower() == "spirits" for seg in parts[:-1]):
            sub = "Spirits"
        else:
            sub = parts[-1]
        out[r["id"]] = {
            "subcategory": sub,
            "group": parts[0],
            "category_path": path,
        }
    return out


# Supplier-name aliases. Any partner whose lowercased name CONTAINS one of these
# substrings is rolled up under a single canonical label. Iteration order matters
# — earlier rules win. Keep keys lowercase.
SUPPLIER_ALIASES = (
    # 1) Anything with "Fyxx" in the vendor tag is the Fyxx house brand —
    #    consolidates "Fyxx | Les Caves de Pyrene", "Fyxx x UMG Bundles",
    #    "Fyxx Operations", etc. into ONE bucket called "Fyxx".
    ("fyxx",            "Fyxx"),
    # 2) UMG umbrella: Union Marketing / OPTICO / Global Brands / Tafaol /
    #    standalone UMG all roll up to UMG.
    ("union marketing", "UMG"),
    ("umg",             "UMG"),
    ("optico",          "UMG"),
    ("global brands",   "UMG"),
    ("tafaol",          "UMG"),
    # 3) Other named vendors that the user highlights individually.
    # Note: 'Bulos Y Zumot & Co. L.L.C' is displayed as 'Zumot' per user spec.
    ("bulos",           "Zumot"),
    ("zumot",           "Zumot"),
    ("arab italian",    "Arab Italian"),
    ("yhc",             "YHC"),
)

# Vendors that the Executive Summary donut highlights individually.
# Anything else is bucketed into "Other".
DONUT_SUPPLIER_HIGHLIGHT = ("UMG", "Fyxx", "Zumot", "Arab Italian", "YHC")


def _normalise_supplier(name):
    """Apply SUPPLIER_ALIASES to a partner name. Returns the canonical label."""
    if not name:
        return name
    low = str(name).strip().lower()
    for needle, canonical in SUPPLIER_ALIASES:
        if needle in low:
            return canonical
    return name


# Bump this whenever SUPPLIER_ALIASES or the donut highlight list changes —
# it forces st.cache_data to invalidate cached supplier resolution so the new
# rules take effect immediately on next deploy instead of waiting for the TTL.
SUPPLIER_RULES_VERSION = 4   # v4 = renamed Bulos display label to Zumot


# Product-supplier lookup — reads the Studio custom field 'x_studio_vendor_tags'
# (free-text vendor tag on the product's Sales tab). 72% coverage vs 13% for
# the Purchase-tab seller_ids approach. Read-only, cached.
@st.cache_data(ttl=HISTORY_TTL, show_spinner=False)
def fetch_product_suppliers(product_ids_tuple, _ttl_bucket,
                             _rules_version=SUPPLIER_RULES_VERSION):
    """For each product, return dict pid -> vendor tag (string).
    Reads `x_studio_vendor_tags` (custom Studio field on product.product).
    Empty / missing → 'No vendor tag'. Aliases via _normalise_supplier().
    The _rules_version arg is purely for cache invalidation — bumping
    SUPPLIER_RULES_VERSION at the top forces a fresh fetch on next render."""
    if not product_ids_tuple:
        return {}
    ids = [int(i) for i in product_ids_tuple if i]
    if not ids:
        return {}
    try:
        prods = kw("product.product", "read", [ids],
                   {"fields": ["id", "x_studio_vendor_tags"]})
    except Exception:
        return {}
    out = {}
    for p in prods:
        raw = p.get("x_studio_vendor_tags")
        # The field is char-type; empty values come back as False or "" in Odoo
        if not raw:
            out[p["id"]] = "No vendor tag"
        else:
            out[p["id"]] = _normalise_supplier(str(raw).strip())
    return out


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
# Display order for channel pills: E-com → Retail → TGR → B2B (B2B at the end).
# Any channel not in this list is appended after, sorted alphabetically.
_CHANNEL_DISPLAY_ORDER = ["E-com", "Retail", "TGR", "B2B", "DF"]
if not df_hist.empty:
    _present = set(df_hist["channel"].dropna().unique().tolist())
    _ordered = [c for c in _CHANNEL_DISPLAY_ORDER if c in _present]
    _extras = sorted(c for c in _present if c not in _CHANNEL_DISPLAY_ORDER)
    all_channels = _ordered + _extras
else:
    all_channels = []


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
quick_options = ["Today", "Yesterday", "MTD", "YTD", "Custom"]
try:
    scope = st.pills(
        "Scope", quick_options, default="Today",
        selection_mode="single", label_visibility="collapsed",
        key="scope_pills_v2",
    )
except Exception:
    try:
        scope = st.segmented_control(
            "Scope", quick_options, default="Today",
            label_visibility="collapsed", key="scope_seg_v2",
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
    """Returns (curr_start, curr_end, prev_start, prev_end, label).
    Active scopes (post-2026-05-08 simplification): Today, MTD, YTD, Custom."""
    main_year = max(sel_years) if sel_years else today.year
    if scope == "Today":
        y = today - timedelta(days=1)
        return today, today, y, y, "Today"
    if scope == "Yesterday":
        y = today - timedelta(days=1)
        d2 = y - timedelta(days=1)
        return y, y, d2, d2, "Yesterday"
    if scope == "MTD":
        # Month-to-Date: 1st of current month → today;
        # prior period is the same number of days in the previous month.
        cs = today.replace(day=1)
        elapsed = (today - cs).days
        prev_last = cs - timedelta(days=1)
        ps = prev_last.replace(day=1)
        pe = ps + timedelta(days=elapsed)
        return cs, today, ps, pe, "MTD"
    if scope == "YTD":
        cs = date(main_year, 1, 1)
        ce = today if main_year == today.year else date(main_year, 12, 31)
        ps = date(main_year - 1, 1, 1)
        pe = ce.replace(year=main_year - 1)
        return cs, ce, ps, pe, f"YTD {main_year}"
    # Custom (or unknown) → use the user's date range
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


# Credit line removed by request. now_local kept — still used elsewhere (e.g. ticker timestamps).
now_local = datetime.now(ZoneInfo(TZ))


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


# Year-performance cards removed by request.
# We still compute `years_with_data` because several multi-year charts
# (YTD trajectory, Monthly YoY, Channel × year) rely on it to know which
# year lines to actually draw.
years_for_cards = sorted(selected_years)
years_with_data = [y for y in years_for_cards
                   if not df[df["year"] == y].empty]


# =============================================================================
# KPI ROW (current scope vs prior period)
# =============================================================================
curr_rev = float(df_curr["amount_total"].sum()) if not df_curr.empty else 0.0
prev_rev = float(df_prev["amount_total"].sum()) if not df_prev.empty else 0.0
curr_vat = float(df_curr["vat"].sum()) if not df_curr.empty and "vat" in df_curr.columns else 0.0
prev_vat = float(df_prev["vat"].sum()) if not df_prev.empty and "vat" in df_prev.columns else 0.0
curr_gross = curr_rev + curr_vat
prev_gross = prev_rev + prev_vat
curr_profit = float(df_curr["margin"].sum()) if not df_curr.empty and "margin" in df_curr.columns else 0.0
prev_profit = float(df_prev["margin"].sum()) if not df_prev.empty and "margin" in df_prev.columns else 0.0
curr_gm_pct = (curr_profit / curr_rev * 100) if curr_rev else 0.0
prev_gm_pct = (prev_profit / prev_rev * 100) if prev_rev else 0.0
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


def render_leaderboard(rows, max_rows=10, color="#19E3B6"):
    """Render an elegant leaderboard from a list of dicts.

    Each row dict:
      name      — primary text
      sub       — small secondary text (optional)
      value     — numeric (used to size the bar and sort)
      value_str — formatted display value (e.g. "84.5K JOD")
      delta_pct — optional float; renders + or - delta chip
    """
    if not rows:
        return "<div class='lb-card'><div class='lb-empty'>No data</div></div>"

    rows = sorted(rows, key=lambda r: r.get("value", 0), reverse=True)[:max_rows]
    max_val = max((r.get("value", 0) for r in rows), default=1) or 1

    rank_class = ["lb-gold", "lb-silver", "lb-bronze"]
    parts = ["<div class='lb-card'>"]
    for i, r in enumerate(rows):
        rank = i + 1
        cls = rank_class[i] if i < 3 else ""
        name = r.get("name") or "—"
        sub = r.get("sub")
        value = r.get("value") or 0
        value_str = r.get("value_str") or f"{value:,.0f}"
        bar_pct = (value / max_val * 100) if max_val else 0

        sub_html = f"<span class='lb-sub'>{sub}</span>" if sub else ""

        delta_html = ""
        d = r.get("delta_pct")
        if d is not None:
            sign = "▲" if d >= 0 else "▼"
            d_cls = "up" if d >= 0 else "dn"
            delta_html = f"<span class='lb-delta {d_cls}'>{sign} {abs(d):.1f}%</span>"

        parts.append(
            f"<div class='lb-row'>"
            f"<span class='lb-rank {cls}'>{rank}</span>"
            f"<div class='lb-body'>"
            f"<div class='lb-name'>{name}{sub_html}</div>"
            f"<div class='lb-bar'>"
            f"<div class='lb-bar-fill' style='width:{bar_pct:.1f}%;"
            f"background:linear-gradient(90deg, {color} 0%, #38BDF8 100%);"
            f"box-shadow:0 0 8px rgba(25,227,182,0.30)'></div>"
            f"</div></div>"
            f"<span class='lb-value'>{value_str}{delta_html}</span>"
            f"</div>"
        )
    parts.append("</div>")
    return "".join(parts)


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


# Daily sparklines for the main KPIs (only when the period spans 2+ days)
_spark_rev = _spark_gross = _spark_gm = _spark_orders = _spark_aov = _spark_cust = None
try:
    if not df_curr.empty and df_curr["day"].nunique() > 1:
        _has_vat = "vat" in df_curr.columns
        _has_margin = "margin" in df_curr.columns
        _agg_dict = {
            "rev": ("amount_total", "sum"),
            "orders": ("amount_total", "count"),
            "cust": ("customer", pd.Series.nunique),
        }
        if _has_vat:
            _agg_dict["vat"] = ("vat", "sum")
        if _has_margin:
            _agg_dict["profit"] = ("margin", "sum")
        _daily_kpi = (df_curr.groupby("day")
                      .agg(**_agg_dict)
                      .sort_index()
                      .reset_index())
        _daily_kpi["aov"] = _daily_kpi.apply(
            lambda r: r["rev"] / r["orders"] if r["orders"] else 0, axis=1
        )
        if _has_vat:
            _daily_kpi["gross"] = _daily_kpi["rev"] + _daily_kpi["vat"]
            _spark_gross = _daily_kpi["gross"].tolist()
        if _has_margin:
            _daily_kpi["gm"] = _daily_kpi.apply(
                lambda r: r["profit"] / r["rev"] * 100 if r["rev"] else 0,
                axis=1,
            )
            _spark_gm = _daily_kpi["gm"].tolist()
        _spark_rev = _daily_kpi["rev"].tolist()
        _spark_orders = _daily_kpi["orders"].tolist()
        _spark_aov = _daily_kpi["aov"].tolist()
        _spark_cust = _daily_kpi["cust"].tolist()
except Exception:
    pass

kpi_html = "<div class='kpi-grid kpi-strip-main' style='margin-top:18px'>"
kpi_html += kpi_card(
    "Net Amount",
    fmt_money(curr_rev, CURRENCY, compact=True),
    delta_html(curr_rev, prev_rev, "vs prior period"),
    f"Prior: {fmt_money(prev_rev, CURRENCY, compact=True)}",
    spark=_spark_rev, spark_color="#19E3B6",
)
kpi_html += kpi_card(
    "Net Amount + VAT",
    fmt_money(curr_gross, CURRENCY, compact=True),
    delta_html(curr_gross, prev_gross, "vs prior period"),
    f"VAT: {fmt_money(curr_vat, CURRENCY, compact=True)}"
    + (f" · Prior gross: {fmt_money(prev_gross, CURRENCY, compact=True)}"
       if prev_gross else ""),
    spark=_spark_gross, spark_color="#5FF5CB",
)
# Gross Margin card — % delta in percentage points, not relative %
_gm_ppt = curr_gm_pct - prev_gm_pct
if prev_gm_pct:
    _gm_arrow = "▲" if _gm_ppt >= 0 else "▼"
    _gm_cls = "kpi-delta-up" if _gm_ppt >= 0 else "kpi-delta-dn"
    _gm_delta_html = (f"<span class='{_gm_cls}'>{_gm_arrow} {abs(_gm_ppt):.1f} ppt</span> "
                      f"<span style='color:#71717A'>vs prior period</span>")
    _gm_foot = f"Prior: {prev_gm_pct:.1f}%"
else:
    _gm_delta_html = "<span style='color:#71717A'>no prior data</span>"
    _gm_foot = ""
kpi_html += kpi_card(
    "Gross margin",
    f"{curr_gm_pct:.1f}%",
    _gm_delta_html,
    (f"Profit: {fmt_money(curr_profit, CURRENCY, compact=True)}"
     + (f" · {_gm_foot}" if _gm_foot else "")),
    spark=_spark_gm, spark_color="#F5B544",
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
(tab_brief, tab_exec, tab_shifts, tab_pace, tab_profit, tab_pnl, tab_sku,
 tab_loss, tab_alerts, tab_trends, tab_channels, tab_customers, tab_cohorts,
 tab_compare, tab_recent) = st.tabs(
    ["  ◆  Brief  ", "  ❖  Executive Summary  ", "  ◷  Online & Shifts  ",
     "  ▲  Pacing  ",
     "  ◯  Profitability  ", "  Σ  P&L  ", "  ❒  Products  ",
     "  ※  Loss Orders  ", "  ⚑  Alerts  ", "  ⌁  Trends  ",
     "  ⌬  Channels  ", "  ◐  Customers  ", "  ⟳  Cohorts  ",
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
    # Top-5 leaderboards — elegant custom HTML with rank, bar, value
    if not df_curr.empty:
        b1, b2, b3 = st.columns(3)

        def _to_lb_rows(series_curr, series_prev=None):
            rows = []
            for name, val in series_curr.items():
                row = {
                    "name": name,
                    "value": float(val),
                    "value_str": fmt_money(val, CURRENCY, compact=True),
                }
                if series_prev is not None and name in series_prev.index:
                    p = float(series_prev[name])
                    if p:
                        row["delta_pct"] = (float(val) - p) / p * 100
                rows.append(row)
            return rows

        ch_curr_s = (df_curr.groupby("channel")["amount_total"].sum()
                     .sort_values(ascending=False).head(5))
        ch_prev_s = (df_prev.groupby("channel")["amount_total"].sum()
                     if not df_prev.empty else pd.Series(dtype=float))
        cu_curr_s = (df_curr.groupby("customer")["amount_total"].sum()
                     .sort_values(ascending=False).head(5))
        cu_prev_s = (df_prev.groupby("customer")["amount_total"].sum()
                     if not df_prev.empty else pd.Series(dtype=float))
        sp_curr_s = (df_curr.groupby("salesperson")["amount_total"].sum()
                     .sort_values(ascending=False).head(5))
        sp_prev_s = (df_prev.groupby("salesperson")["amount_total"].sum()
                     if not df_prev.empty else pd.Series(dtype=float))

        with b1:
            st.markdown("<div class='sec'><h3>Top channels</h3></div>",
                        unsafe_allow_html=True)
            st.markdown(render_leaderboard(_to_lb_rows(ch_curr_s, ch_prev_s)),
                        unsafe_allow_html=True)
        with b2:
            st.markdown("<div class='sec'><h3>Top customers</h3></div>",
                        unsafe_allow_html=True)
            st.markdown(render_leaderboard(_to_lb_rows(cu_curr_s, cu_prev_s)),
                        unsafe_allow_html=True)
        with b3:
            st.markdown("<div class='sec'><h3>Top salespeople</h3></div>",
                        unsafe_allow_html=True)
            st.markdown(render_leaderboard(_to_lb_rows(sp_curr_s, sp_prev_s)),
                        unsafe_allow_html=True)


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
        st.markdown("<div class='sec'><h3>Revenue by product category</h3>"
                    f"<div class='sec-sub'>{scope_label} · sub-category mix</div></div>",
                    unsafe_allow_html=True)
        if df_curr.empty:
            st.info("No data in selected window.")
        else:
            # Pull order lines for the active scope (cached), filter to
            # the channel-filtered orders in df_curr, then aggregate by
            # product sub-category (Wine, Whisky, Cigars, Food Menu Items, ...)
            _ex_start_utc, _ex_end_utc = _date_window_utc(curr_start, curr_end, TZ)
            try:
                _ex_lines = fetch_order_lines_window(
                    _ex_start_utc.strftime("%Y-%m-%d %H:%M:%S"),
                    _ex_end_utc.strftime("%Y-%m-%d %H:%M:%S"),
                    hist_bucket,
                )
            except Exception:
                _ex_lines = []
            if not _ex_lines:
                st.info("Product line data unavailable for this window.")
            else:
                _ex_ldf = pd.DataFrame(_ex_lines)
                # Keep only lines whose (source, order_id) is in df_curr
                _allowed = set(zip(
                    df_curr["source"].astype(str),
                    df_curr["order_id"].fillna(-1).astype(int),
                ))
                _ex_ldf = _ex_ldf[_ex_ldf.apply(
                    lambda r: (r["source"], int(r["order_id"]) if pd.notna(r["order_id"]) else -1)
                              in _allowed,
                    axis=1,
                )]
                if _ex_ldf.empty:
                    st.info("No product line data for the active channel selection.")
                else:
                    # Resolve categories (both subcategory leaf and top group)
                    _ex_pids = tuple(sorted({
                        int(p) for p in _ex_ldf["product_id"].dropna().tolist()
                    }))
                    _ex_cats = fetch_product_categories(_ex_pids, hist_bucket)

                    def _pid_get(pid, key):
                        if pid is None or pd.isna(pid):
                            return ""
                        return (_ex_cats.get(int(pid), {}).get(key, "") or "")

                    _ex_ldf["subcategory"] = _ex_ldf["product_id"].map(
                        lambda p: _pid_get(p, "subcategory"))
                    _ex_ldf["group"] = _ex_ldf["product_id"].map(
                        lambda p: _pid_get(p, "group"))

                    # ---- Map every line to one of the 7 display categories
                    # in the order the user asked for ----
                    def _display_cat(sub, group):
                        s = (sub or "").strip().lower()
                        g = (group or "").strip().lower()
                        if "btg" in s:
                            # Separate Wine BTG (by-the-glass) from Spirits BTG
                            if "wine" in s:
                                return "Wine BTG"
                            return "Spirits BTG"
                        # 'Tasting Cards' = "By The Glass Card Top-Up" SKUs;
                        # per user spec these roll into the Wine BTG bucket.
                        if "tasting card" in s:
                            return "Wine BTG"
                        if s in ("wine", "wines"):
                            return "Wines"
                        if s == "spirits":
                            return "Spirits"
                        if "cocktail" in s:
                            return "Cocktails"
                        if "cigar" in s:
                            return "Cigars"
                        if g == "food":
                            return "Food"
                        return "Other"

                    _ex_ldf["display_cat"] = [
                        _display_cat(sc, gr)
                        for sc, gr in zip(_ex_ldf["subcategory"], _ex_ldf["group"])
                    ]

                    # User-defined sequence (drop empties; "Other" only if any)
                    CAT_SEQUENCE = [
                        "Wines", "Spirits", "Cocktails", "Food", "Cigars",
                        "Spirits BTG", "Wine BTG", "Other",
                    ]
                    cat_rev_raw = _ex_ldf.groupby("display_cat")["revenue"].sum()
                    cat_rev = cat_rev_raw.reindex(CAT_SEQUENCE).fillna(0)
                    cat_rev = cat_rev[cat_rev > 0]  # don't render zero slices

                    # Per-category neon palette aligned to the sequence
                    _DISPLAY_CAT_COLORS = {
                        "Wines":       "#A78BFA",  # violet (bottled wine)
                        "Spirits":     "#F5B544",  # gold
                        "Cocktails":   "#EC4899",  # rose
                        "Food":        "#19E3B6",  # neon teal
                        "Cigars":      "#F87171",  # warm red
                        "Spirits BTG": "#38BDF8",  # sky blue
                        "Wine BTG":    "#C4B5FD",  # light lavender (echoes Wines)
                        "Other":       "#52525B",  # muted grey
                    }
                    cat_colors = [_DISPLAY_CAT_COLORS.get(c, "#52525B")
                                  for c in cat_rev.index]

                    total_cat_rev = float(cat_rev.sum())
                    fig = go.Figure(data=[go.Pie(
                        labels=cat_rev.index.tolist(),
                        values=cat_rev.values.tolist(),
                        sort=False,           # preserve the user's sequence
                        direction="clockwise",
                        hole=0.7,
                        texttemplate="%{value:,.0f}<br>%{percent}",
                        marker=dict(colors=cat_colors,
                                    line=dict(color=PALETTE["surface"], width=3)),
                        hovertemplate="<b>%{label}</b><br>"
                                      "%{value:,.0f} " + CURRENCY +
                                      "<br>%{percent}<extra></extra>",
                        textfont=dict(size=11, color=PALETTE["text"]),
                    )])
                    fig.update_layout(annotations=[dict(
                        text=f"<b>{fmt_money(total_cat_rev, CURRENCY, compact=True)}</b>"
                             f"<br><span style='font-size:10px;color:#A1A1AA'>Categories</span>",
                        showarrow=False, font=dict(size=14, color=PALETTE["text"]))])
                    st.plotly_chart(style_fig(fig, height=340),
                                    use_container_width=True)

    # ---- Revenue by supplier (third Exec Summary chart) ----
    st.markdown("<div class='sec' style='margin-top:14px'>"
                "<h3>Revenue by supplier</h3>"
                f"<div class='sec-sub'>{scope_label} · top suppliers by net revenue</div></div>",
                unsafe_allow_html=True)
    if df_curr.empty:
        st.info("No data in selected window.")
    else:
        _sup_start_utc, _sup_end_utc = _date_window_utc(curr_start, curr_end, TZ)
        try:
            _sup_lines = fetch_order_lines_window(
                _sup_start_utc.strftime("%Y-%m-%d %H:%M:%S"),
                _sup_end_utc.strftime("%Y-%m-%d %H:%M:%S"),
                hist_bucket,
            )
        except Exception:
            _sup_lines = []
        if not _sup_lines:
            st.info("Product line data unavailable for this window.")
        else:
            _sup_ldf = pd.DataFrame(_sup_lines)
            # Apply channel slicer (same trick as the category donut)
            _allowed_sup = set(zip(
                df_curr["source"].astype(str),
                df_curr["order_id"].fillna(-1).astype(int),
            ))
            _sup_ldf = _sup_ldf[_sup_ldf.apply(
                lambda r: (r["source"],
                           int(r["order_id"]) if pd.notna(r["order_id"]) else -1)
                          in _allowed_sup,
                axis=1,
            )]
            if _sup_ldf.empty:
                st.info("No product line data for the active channel selection.")
            else:
                _sup_pids = tuple(sorted({
                    int(p) for p in _sup_ldf["product_id"].dropna().tolist()
                }))
                with st.spinner("Resolving suppliers..."):
                    _supplier_map = fetch_product_suppliers(_sup_pids, hist_bucket)
                _sup_ldf["supplier"] = _sup_ldf["product_id"].map(
                    lambda p: _supplier_map.get(int(p), "No vendor tag")
                              if (p is not None and not pd.isna(p))
                              else "No vendor tag"
                )
                # Aggregate by raw supplier first (preserves all real names for the table)
                sup_rev_full = (_sup_ldf.groupby("supplier")["revenue"]
                                .sum().sort_values(ascending=False))

                # ---- Donut data: bucket everything not in the highlight list as "Other" ----
                _sup_ldf["supplier_display"] = _sup_ldf["supplier"].map(
                    lambda s: s if s in DONUT_SUPPLIER_HIGHLIGHT else "Other"
                )
                sup_rev_donut = (_sup_ldf.groupby("supplier_display")["revenue"]
                                 .sum())
                # Fixed sequence: UMG, Fyxx, Bulos, Arab Italian, YHC, Other
                donut_sequence = list(DONUT_SUPPLIER_HIGHLIGHT) + ["Other"]
                sup_rev_donut = (sup_rev_donut.reindex(donut_sequence)
                                              .fillna(0))
                sup_rev_donut = sup_rev_donut[sup_rev_donut > 0]

                # Stable colour per named vendor (sequence-aligned)
                _SUPPLIER_DONUT_COLORS = {
                    "UMG":          "#19E3B6",  # neon teal
                    "Fyxx":         "#F5B544",  # gold
                    "Zumot":        "#A78BFA",  # violet
                    "Arab Italian": "#38BDF8",  # sky blue
                    "YHC":          "#EC4899",  # rose
                    "Other":        "#52525B",  # muted grey
                }
                donut_colors = [_SUPPLIER_DONUT_COLORS.get(c, "#52525B")
                                for c in sup_rev_donut.index]

                sa, sb = st.columns([2, 3])
                with sa:
                    total_sup = float(sup_rev_donut.sum())
                    fig = go.Figure(data=[go.Pie(
                        labels=sup_rev_donut.index.tolist(),
                        values=sup_rev_donut.values.tolist(),
                        sort=False,
                        direction="clockwise",
                        hole=0.65,
                        texttemplate="%{value:,.0f}<br>%{percent}",
                        marker=dict(colors=donut_colors,
                                    line=dict(color=PALETTE["surface"], width=3)),
                        hovertemplate="<b>%{label}</b><br>"
                                      "%{value:,.0f} " + CURRENCY +
                                      "<br>%{percent}<extra></extra>",
                        textfont=dict(size=11, color=PALETTE["text"]),
                    )])
                    fig.update_layout(annotations=[dict(
                        text=f"<b>{fmt_money(total_sup, CURRENCY, compact=True)}</b>"
                             f"<br><span style='font-size:10px;color:#A1A1AA'>"
                             f"{sup_rev_full.shape[0]} suppliers</span>",
                        showarrow=False, font=dict(size=14, color=PALETTE["text"]))])
                    st.plotly_chart(style_fig(fig, height=400),
                                    use_container_width=True)

                with sb:
                    st.markdown("<div class='sec'><h3>Top 15 suppliers</h3>"
                                "<div class='sec-sub'>All vendors, not just the donut "
                                "highlights — drill into 'Other'</div></div>",
                                unsafe_allow_html=True)
                    top15_sup = sup_rev_full.head(15).reset_index()
                    top15_sup.columns = ["Supplier", f"Revenue ({CURRENCY})"]
                    _max_sup = top15_sup[f"Revenue ({CURRENCY})"].max() or 1
                    st.dataframe(
                        top15_sup, use_container_width=True, hide_index=True,
                        height=400,
                        column_config={
                            f"Revenue ({CURRENCY})": st.column_config.ProgressColumn(
                                f"Revenue ({CURRENCY})", format="%,.0f",
                                min_value=0, max_value=float(_max_sup)),
                        },
                    )


# -------- Pacing & Forecast --------
# -------- Online & Shifts --------
with tab_shifts:
    st.markdown(
        "<style>"
        ".insight-card{background:linear-gradient(135deg,rgba(25,227,182,0.07),"
        "rgba(167,139,250,0.05));border:1px solid #23232B;border-radius:14px;"
        "padding:15px 20px;margin-top:14px}"
        ".insight-title{font-size:11px;font-weight:700;letter-spacing:0.14em;"
        "text-transform:uppercase;color:#19E3B6;margin-bottom:8px}"
        ".insight-list{margin:0;padding-left:18px;color:#D4D4D8;font-size:13px;"
        "line-height:1.95}"
        ".insight-list li{margin-bottom:1px}"
        ".shift-table{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:4px}"
        ".shift-table th{text-align:right;padding:8px 12px;color:#71717A;font-size:10px;"
        "text-transform:uppercase;letter-spacing:0.07em;border-bottom:1px solid #23232B}"
        ".shift-table th:first-child{text-align:left}"
        ".shift-table td{text-align:right;padding:7px 12px;color:#E4E4E7;"
        "border-bottom:1px solid #18181f;font-variant-numeric:tabular-nums}"
        ".shift-table td:first-child{text-align:left;color:#A1A1AA}"
        ".shift-table tr.tot td{border-top:1px solid #2D2D37;font-weight:700;"
        "color:#F4F4F5;background:rgba(25,227,182,0.05)}"
        "</style>",
        unsafe_allow_html=True,
    )

    # ===== Linked to the global filters: scope window + channels + years =====
    # Confirmed orders already reflect year + channel + scope (df_curr/df_prev).
    # Drafts + cancellations aren't in that pipeline, so they're fetched for the
    # SAME window and run through the SAME channel filter below.
    sh_start, sh_end = curr_start, curr_end
    win_days = max(1, (sh_end - sh_start).days + 1)
    is_online_only = set(selected_channels) == {"E-com"}
    noun = "online orders" if is_online_only else "orders"
    show_day_labels = win_days <= 16

    def _with_shift(d):
        if d.empty:
            return d
        x = d.copy()
        x["hour"] = x["dt_local"].dt.hour
        x["shift"] = x["hour"].apply(_shift_of_hour)
        return x

    conf_cur = _with_shift(df_curr)
    conf_prv = _with_shift(df_prev)

    _s_utc, _e_utc = _date_window_utc(sh_start, sh_end, TZ)
    sh_rows = fetch_online_draft_orders(
        _s_utc.strftime("%Y-%m-%d %H:%M:%S"),
        _e_utc.strftime("%Y-%m-%d %H:%M:%S"),
        hist_bucket,
    )
    if sh_rows:
        sdf = pd.DataFrame(sh_rows)
        sdf = sdf[sdf["channel"].isin(selected_channels)]   # honour channel pills
    else:
        sdf = pd.DataFrame(columns=["state", "channel", "date_order"])
    if not sdf.empty:
        sdf["dt_local"] = sdf["date_order"].apply(lambda s: _to_local_dt(s, TZ))
        sdf["day"] = sdf["dt_local"].dt.date
        draft_cur = sdf[sdf["state"].isin(["draft", "sent"])]
        cancel_cur = sdf[sdf["state"] == "cancel"]
    else:
        draft_cur = cancel_cur = sdf

    days = [sh_start + timedelta(days=i) for i in range(win_days)]
    day_labels = [d.strftime("%a %d") for d in days]

    n_orders = len(conf_cur)
    n_orders_prev = len(conf_prv)
    n_draft = len(draft_cur)
    n_cancel = len(cancel_cur)

    def _sc(d, shift):
        return int((d["shift"] == shift).sum()) if (not d.empty and "shift" in d) else 0

    n_day = _sc(conf_cur, SHIFT_DAY_LABEL)
    n_eve = _sc(conf_cur, SHIFT_EVE_LABEL)
    n_off = _sc(conf_cur, SHIFT_OFF_LABEL)
    day_prev = _sc(conf_prv, SHIFT_DAY_LABEL)
    eve_prev = _sc(conf_prv, SHIFT_EVE_LABEL)

    # ---------- Header (mirrors the active filters) ----------
    if not selected_channels or set(selected_channels) == set(all_channels):
        ch_note = "all channels"
    else:
        ch_note = ", ".join(selected_channels)
    title = ("Online Orders &amp; Shift Analytics" if is_online_only
             else "Orders &amp; Shift Analytics")
    st.markdown(
        f"<div class='sec'><h3>{title}</h3>"
        f"<div class='sec-sub'>{scope_label} · {sh_start:%d %b} → "
        f"{sh_end:%d %b %Y} ({win_days} days) &nbsp;·&nbsp; Day 10:00–17:00 "
        "&nbsp;·&nbsp; Evening 17:00–01:00 &nbsp;·&nbsp; "
        f"channels: {ch_note}</div></div>",
        unsafe_allow_html=True,
    )

    # ---------- KPI strip ----------
    avg_per_day = n_orders / win_days if win_days else 0
    if not conf_cur.empty:
        by_day = conf_cur.groupby("day").size()
        busiest_day = by_day.idxmax()
        busiest_n = int(by_day.max())
        busiest_lbl = busiest_day.strftime("%a %d %b")
    else:
        busiest_lbl, busiest_n = "—", 0
    day_share = (n_day / n_orders * 100) if n_orders else 0
    eve_share = (n_eve / n_orders * 100) if n_orders else 0

    kpis = "<div class='kpi-grid' style='margin-top:6px'>"
    kpis += kpi_card(
        "Orders · period", f"{n_orders:,}",
        delta_html(n_orders, n_orders_prev, "vs prior period"),
        f"Prior: {n_orders_prev:,}")
    kpis += kpi_card(
        "Day shift · 10–17", f"{n_day:,}",
        delta_html(n_day, day_prev, "vs prior period"),
        f"{day_share:.0f}% of orders")
    kpis += kpi_card(
        "Evening shift · 17–01", f"{n_eve:,}",
        delta_html(n_eve, eve_prev, "vs prior period"),
        f"{eve_share:.0f}% of orders")
    kpis += kpi_card(
        "Busiest day", busiest_lbl,
        f"{busiest_n:,} orders",
        f"Avg {avg_per_day:.1f} / day")
    kpis += kpi_card(
        "Draft orders", f"{n_draft:,}",
        "", "Odoo quotations (draft / sent)")
    kpis += kpi_card(
        "Cancelled", f"{n_cancel:,}",
        "", "Orders placed then voided")
    kpis += "</div>"
    st.markdown(kpis, unsafe_allow_html=True)

    # ---------- Smart insights ----------
    insights = []
    if n_orders:
        if n_eve >= n_day:
            dom, dom_n, oth_n = "evening", n_eve, n_day
        else:
            dom, dom_n, oth_n = "day", n_day, n_eve
        dom_share = dom_n / n_orders * 100 if n_orders else 0
        insights.append(
            f"The <b>{dom} shift</b> drives <b>{dom_share:.0f}%</b> of {noun} "
            f"this period — <b>{dom_n:,}</b> vs <b>{oth_n:,}</b> on the "
            "other shift.")
        ph = conf_cur.groupby("hour").size()
        if not ph.empty:
            peak_h = int(ph.idxmax())
            peak_hn = int(ph.max())
            rush = "evening" if (peak_h >= 17 or peak_h < 1) else "afternoon"
            insights.append(
                f"Peak hour is <b>{peak_h:02d}:00</b> with <b>{peak_hn:,}</b> "
                f"orders — concentrate staffing around the {rush} rush.")
        if n_orders_prev:
            d = (n_orders - n_orders_prev) / n_orders_prev * 100
            insights.append(
                f"Volume is <b>{'up' if d >= 0 else 'down'} "
                f"{abs(d):.0f}%</b> vs the prior period "
                f"({n_orders:,} vs {n_orders_prev:,}).")
        if not conf_cur.empty:
            bd = conf_cur.groupby("day").size()
            qd = bd.idxmin()
            insights.append(
                f"Busiest day <b>{busiest_lbl}</b> ({busiest_n:,}); quietest "
                f"<b>{qd:%a %d %b}</b> ({int(bd.min()):,}).")
        placed = n_orders + n_cancel
        if placed:
            insights.append(
                f"<b>{n_cancel:,}</b> orders were cancelled this period — "
                f"<b>{n_cancel / placed * 100:.0f}%</b> of all placed.")
        if n_off:
            insights.append(
                f"<b>{n_off:,}</b> orders landed off-shift (01:00–10:00).")
        insights.append(
            f"<b>{n_draft:,}</b> draft quotation(s) pending in Odoo."
            if n_draft else
            "No draft quotations are currently pending in Odoo.")
    else:
        insights.append(f"No {noun} matched the current filters in this period.")
    items = "".join(f"<li>{t}</li>" for t in insights)
    st.markdown(
        "<div class='insight-card'><div class='insight-title'>◆ Smart insights"
        f"</div><ul class='insight-list'>{items}</ul></div>",
        unsafe_allow_html=True,
    )

    # ---------- Daily orders by shift (stacked) ----------
    st.markdown(
        "<div class='sec' style='margin-top:18px'><h3>Daily orders by shift</h3>"
        "<div class='sec-sub'>Stacked — day vs evening vs off-hours</div></div>",
        unsafe_allow_html=True)
    if n_orders:
        fig = go.Figure()
        for shift in SHIFT_ORDER:
            yvals = [int(((conf_cur["day"] == d) &
                          (conf_cur["shift"] == shift)).sum()) for d in days]
            if shift == SHIFT_OFF_LABEL and sum(yvals) == 0:
                continue
            fig.add_trace(go.Bar(
                x=day_labels, y=yvals, name=shift,
                marker=dict(color=SHIFT_COLORS[shift]),
                text=[v if (v and show_day_labels) else "" for v in yvals],
                texttemplate="%{text}", textposition="inside",
                insidetextanchor="middle",
                textfont=dict(size=11, color="#0A0A0B"),
                hovertemplate=f"<b>%{{x}}</b><br>{shift}: %{{y}} orders<extra></extra>",
            ))
        fig.update_layout(barmode="stack",
                          bargap=0.32 if win_days <= 14 else 0.08)
        st.plotly_chart(style_fig(fig, height=350), use_container_width=True)
    else:
        st.info("No orders match the current filters.")

    # ---------- Shift donut + hour-of-day ----------
    c1, c2 = st.columns([2, 3])
    with c1:
        st.markdown(
            "<div class='sec'><h3>Shift split</h3>"
            "<div class='sec-sub'>Share of orders</div></div>",
            unsafe_allow_html=True)
        if n_orders:
            labels = [SHIFT_DAY_LABEL, SHIFT_EVE_LABEL]
            vals = [n_day, n_eve]
            cols = [SHIFT_COLORS[SHIFT_DAY_LABEL], SHIFT_COLORS[SHIFT_EVE_LABEL]]
            if n_off:
                labels.append(SHIFT_OFF_LABEL)
                vals.append(n_off)
                cols.append(SHIFT_COLORS[SHIFT_OFF_LABEL])
            fig = go.Figure(go.Pie(
                labels=labels, values=vals, hole=0.64, sort=False,
                marker=dict(colors=cols,
                            line=dict(color=PALETTE["surface"], width=2)),
                textinfo="percent", textfont=dict(size=12, color="#0A0A0B"),
                hovertemplate="%{label}<br>%{value} orders (%{percent})<extra></extra>",
            ))
            fig.update_layout(annotations=[dict(
                text=f"<b style='color:#F4F4F5'>{n_orders:,}</b><br>"
                     "<span style='font-size:10px;color:#A1A1AA'>orders</span>",
                x=0.5, y=0.5, showarrow=False, font=dict(size=20))])
            st.plotly_chart(style_fig(fig, height=300), use_container_width=True)
        else:
            st.info("No data.")
    with c2:
        st.markdown(
            "<div class='sec'><h3>Orders by hour of day</h3>"
            "<div class='sec-sub'>Bar colour marks the shift each hour belongs to</div></div>",
            unsafe_allow_html=True)
        if n_orders:
            hours = list(range(24))
            hv = conf_cur.groupby("hour").size().reindex(hours, fill_value=0)
            colors = [SHIFT_COLORS[_shift_of_hour(h)] for h in hours]
            fig = go.Figure(go.Bar(
                x=[f"{h:02d}" for h in hours], y=hv.values,
                marker=dict(color=colors),
                hovertemplate="%{x}:00<br>%{y} orders<extra></extra>",
            ))
            st.plotly_chart(style_fig(fig, height=300, show_legend=False),
                            use_container_width=True)
        else:
            st.info("No data.")

    # ---------- Weekday × hour heatmap (scales to any window) ----------
    st.markdown(
        "<div class='sec' style='margin-top:14px'><h3>Order intensity · weekday × hour"
        "</h3><div class='sec-sub'>Order counts aggregated across the period; "
        "brighter = busier</div></div>",
        unsafe_allow_html=True)
    if n_orders:
        hm = conf_cur.copy()
        hm["dow"] = hm["dt_local"].dt.day_name().str[:3]
        mat = hm.groupby(["dow", "hour"]).size().reset_index(name="n")
        order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        piv = (mat.pivot(index="dow", columns="hour", values="n")
               .reindex(order).reindex(columns=range(24)).fillna(0))
        text_z = [[(f"{int(v)}" if v else "") for v in row] for row in piv.values]
        fig = go.Figure(go.Heatmap(
            z=piv.values, x=[f"{h:02d}" for h in range(24)], y=order,
            colorscale=[[0, "#0A0A0B"], [0.45, "#3a2f5e"], [1, "#A78BFA"]],
            text=text_z, texttemplate="%{text}",
            textfont=dict(size=9, color="#E4E4E7"),
            hovertemplate="%{y} · %{x}:00<br>%{z} orders<extra></extra>",
            showscale=False, xgap=1, ygap=2,
        ))
        st.plotly_chart(style_fig(fig, height=300, show_legend=False),
                        use_container_width=True)
    else:
        st.info("No data.")

    # ---------- Orders vs draft daily trend ----------
    st.markdown(
        "<div class='sec' style='margin-top:14px'><h3>Orders vs draft · daily</h3>"
        "<div class='sec-sub'>Order counts across the period</div></div>",
        unsafe_allow_html=True)
    on_daily = [int((conf_cur["day"] == d).sum()) if not conf_cur.empty else 0
                for d in days]
    dr_daily = [int((draft_cur["day"] == d).sum()) if not draft_cur.empty else 0
                for d in days]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=day_labels, y=on_daily, name="Orders",
        mode="lines+markers+text" if show_day_labels else "lines+markers",
        line=dict(width=2.6, color=PALETTE["neon"], shape="spline", smoothing=0.5),
        marker=dict(size=7, color=PALETTE["neon"]),
        text=on_daily if show_day_labels else None, textposition="top center",
        textfont=dict(color=PALETTE["neon"], size=10), cliponaxis=False,
        hovertemplate="%{x}<br>%{y} orders<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=day_labels, y=dr_daily, name="Draft",
        mode="lines+markers",
        line=dict(width=2.2, color=PALETTE["sky"], dash="dot"),
        marker=dict(size=6, color=PALETTE["sky"]),
        hovertemplate="%{x}<br>%{y} draft<extra></extra>"))
    st.plotly_chart(style_fig(fig, height=300), use_container_width=True)

    # ---------- Per-day breakdown table ----------
    MAXROWS = 45
    capped = win_days > MAXROWS
    days_tbl = days[-MAXROWS:] if capped else days
    cap_note = (f"<div class='sec-sub'>Showing the most recent {MAXROWS} of "
                f"{win_days} days</div>" if capped else "")
    st.markdown(
        "<div class='sec' style='margin-top:14px'><h3>Per-day breakdown</h3>"
        "<div class='sec-sub'>Orders by shift, plus drafts &amp; "
        f"cancellations</div>{cap_note}</div>",
        unsafe_allow_html=True)
    tot = {"day": 0, "eve": 0, "off": 0, "on": 0, "dr": 0, "cn": 0}
    body = ""
    for d in days_tbl:
        dd = conf_cur[conf_cur["day"] == d] if not conf_cur.empty else conf_cur
        cday = _sc(dd, SHIFT_DAY_LABEL)
        ceve = _sc(dd, SHIFT_EVE_LABEL)
        coff = _sc(dd, SHIFT_OFF_LABEL)
        con = cday + ceve + coff
        cdr = int((draft_cur["day"] == d).sum()) if not draft_cur.empty else 0
        ccn = int((cancel_cur["day"] == d).sum()) if not cancel_cur.empty else 0
        tot["day"] += cday; tot["eve"] += ceve; tot["off"] += coff
        tot["on"] += con; tot["dr"] += cdr; tot["cn"] += ccn
        body += (f"<tr><td>{d:%a %d %b}</td><td>{cday}</td><td>{ceve}</td>"
                 f"<td>{coff}</td><td><b>{con}</b></td><td>{cdr}</td>"
                 f"<td>{ccn}</td></tr>")
    body += (f"<tr class='tot'><td>Total</td><td>{tot['day']}</td>"
             f"<td>{tot['eve']}</td><td>{tot['off']}</td><td>{tot['on']}</td>"
             f"<td>{tot['dr']}</td><td>{tot['cn']}</td></tr>")
    st.markdown(
        "<table class='shift-table'><thead><tr>"
        "<th>Date</th><th>Day 10–17</th><th>Evening 17–01</th><th>Off 01–10</th>"
        "<th>Total orders</th><th>Draft</th><th>Cancelled</th>"
        f"</tr></thead><tbody>{body}</tbody></table>",
        unsafe_allow_html=True)

    # ======================= DELIVERY PERFORMANCE =======================
    st.markdown(
        "<div class='sec' style='margin-top:24px'><h3>Delivery performance</h3>"
        "<div class='sec-sub'>Real delivery orders (excludes in-store pickups) "
        "linked to sales placed in this period &nbsp;·&nbsp; lead time = order "
        "placed → delivery completed</div></div>",
        unsafe_allow_html=True)

    dlv_rows = fetch_delivery_orders(
        _s_utc.strftime("%Y-%m-%d %H:%M:%S"),
        _e_utc.strftime("%Y-%m-%d %H:%M:%S"),
        hist_bucket,
    )
    if dlv_rows:
        ddf = pd.DataFrame(dlv_rows)
        ddf = ddf[ddf["channel"].isin(selected_channels)]   # honour channel pills
    else:
        ddf = pd.DataFrame(columns=[
            "state", "channel", "carrier", "carrier_price",
            "order_date", "date_done", "lead_hours", "late"])

    if not ddf.empty:
        ddf["order_dt"] = ddf["order_date"].apply(
            lambda s: _to_local_dt(s, TZ) if s else None)
        ddf["shift"] = ddf["order_dt"].apply(
            lambda d: _shift_of_hour(d.hour) if d is not None else None)
        ddf["day"] = ddf["order_dt"].apply(
            lambda d: d.date() if d is not None else None)
        # completion timestamps drive the fleet-capacity model below
        ddf["done_dt"] = ddf["date_done"].apply(
            lambda s: _to_local_dt(s, TZ) if s else None)
        ddf["done_hour"] = ddf["done_dt"].apply(
            lambda d: d.hour if d is not None else None)
        ddf["done_day"] = ddf["done_dt"].apply(
            lambda d: d.date() if d is not None else None)

    done_d = ddf[ddf["state"] == "done"] if not ddf.empty else ddf
    pend_d = (ddf[ddf["state"].isin(["assigned", "confirmed", "waiting"])]
              if not ddf.empty else ddf)
    canc_d = ddf[ddf["state"] == "cancel"] if not ddf.empty else ddf
    lead = done_d["lead_hours"].dropna().tolist() if not done_d.empty else []

    def _fmt_h(h):
        if h is None:
            return "—"
        if h < 1:
            return f"{h * 60:.0f} min"
        if h < 48:
            return f"{h:.1f} h"
        return f"{h / 24:.1f} d"

    def _median(xs):
        if not xs:
            return None
        xs = sorted(xs)
        n = len(xs)
        return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2

    med_lead = _median(lead)
    p90_lead = (sorted(lead)[min(len(lead) - 1, int(len(lead) * 0.9))]
                if lead else None)
    within2 = (sum(1 for x in lead if x <= 2) / len(lead) * 100) if lead else 0
    within24 = (sum(1 for x in lead if x <= 24) / len(lead) * 100) if lead else 0
    SHIFT_SHORT = {SHIFT_DAY_LABEL: "day", SHIFT_EVE_LABEL: "evening",
                   SHIFT_OFF_LABEL: "off-hours"}

    if ddf.empty:
        st.info("No delivery orders linked to sales under the current filters.")
    else:
        if not ddf.empty and "carrier" in ddf:
            cm_all = ddf["carrier"].value_counts()
            top_carrier = str(cm_all.index[0])
            top_share = cm_all.iloc[0] / len(ddf) * 100
        else:
            top_carrier, top_share = "—", 0

        dk = "<div class='kpi-grid' style='margin-top:6px'>"
        dk += kpi_card("Deliveries · period", f"{len(ddf):,}",
                       "", f"{len(done_d):,} completed")
        dk += kpi_card("Typical lead time", _fmt_h(med_lead),
                       "median order → delivered", f"p90: {_fmt_h(p90_lead)}")
        dk += kpi_card("Within 2 hours", f"{within2:.0f}%",
                       "of completed deliveries", f"Within 24h: {within24:.0f}%")
        dk += kpi_card("In transit", f"{len(pend_d):,}",
                       "assigned / awaiting", "not yet delivered")
        dk += kpi_card("Top carrier", top_carrier,
                       f"{top_share:.0f}% of deliveries", "")
        dk += kpi_card("Cancelled", f"{len(canc_d):,}",
                       "", "delivery orders voided")
        dk += "</div>"
        st.markdown(dk, unsafe_allow_html=True)

        # ---- Delivery insights ----
        dins = []
        if lead:
            dins.append(
                f"Typical delivery completes in <b>{_fmt_h(med_lead)}</b> "
                f"(median); 90% land within <b>{_fmt_h(p90_lead)}</b>.")
            dins.append(
                f"<b>{within2:.0f}%</b> of deliveries finish within 2 hours and "
                f"<b>{within24:.0f}%</b> within a day.")
            sh_med = {}
            for sh in SHIFT_ORDER:
                vals = done_d[done_d["shift"] == sh]["lead_hours"].dropna().tolist()
                if vals:
                    sh_med[sh] = _median(vals)
            if len(sh_med) >= 2:
                fast = min(sh_med, key=sh_med.get)
                slow = max(sh_med, key=sh_med.get)
                dins.append(
                    f"Orders placed in the <b>{SHIFT_SHORT.get(fast, fast)}</b> "
                    f"shift are delivered fastest (median "
                    f"{_fmt_h(sh_med[fast])}), slowest from the "
                    f"<b>{SHIFT_SHORT.get(slow, slow)}</b> shift "
                    f"({_fmt_h(sh_med[slow])}).")
            slowtail = [x for x in lead if x > 48]
            if slowtail:
                dins.append(
                    f"<b>{len(slowtail)}</b> deliveries took over 2 days "
                    f"(slowest {_fmt_h(max(lead))}) — these drag the average to "
                    f"{_fmt_h(sum(lead) / len(lead))}; worth investigating.")
        if len(pend_d):
            dins.append(
                f"<b>{len(pend_d)}</b> deliveries are currently in transit / "
                "awaiting dispatch.")
        if len(canc_d):
            dins.append(
                f"<b>{len(canc_d)}</b> delivery orders were cancelled this period.")
        if not dins:
            dins.append("No completed deliveries with usable timing in this period.")
        ditems = "".join(f"<li>{t}</li>" for t in dins)
        st.markdown(
            "<div class='insight-card'><div class='insight-title'>◆ Delivery "
            f"insights</div><ul class='insight-list'>{ditems}</ul></div>",
            unsafe_allow_html=True)

        # ---- Distribution + carrier ----
        d1, d2 = st.columns(2)
        with d1:
            st.markdown(
                "<div class='sec'><h3>Delivery-time distribution</h3>"
                "<div class='sec-sub'>Completed deliveries by lead-time bucket</div></div>",
                unsafe_allow_html=True)
            if lead:
                buckets = ["<1h", "1–2h", "2–6h", "6–24h", "1–2d", ">2d"]

                def _bk(h):
                    if h < 1:
                        return "<1h"
                    if h < 2:
                        return "1–2h"
                    if h < 6:
                        return "2–6h"
                    if h < 24:
                        return "6–24h"
                    if h < 48:
                        return "1–2d"
                    return ">2d"
                bc = {b: 0 for b in buckets}
                for x in lead:
                    bc[_bk(x)] += 1
                fig = go.Figure(go.Bar(
                    x=buckets, y=[bc[b] for b in buckets],
                    marker=dict(color=PALETTE["neon"]),
                    text=[bc[b] or "" for b in buckets],
                    texttemplate="%{text}", textposition="outside",
                    textfont=dict(color=PALETTE["text_dim"], size=10),
                    cliponaxis=False,
                    hovertemplate="%{x}<br>%{y} deliveries<extra></extra>"))
                st.plotly_chart(style_fig(fig, height=300, show_legend=False),
                                use_container_width=True)
            else:
                st.info("No completed deliveries.")
        with d2:
            st.markdown(
                "<div class='sec'><h3>By carrier</h3>"
                "<div class='sec-sub'>Share of delivery orders</div></div>",
                unsafe_allow_html=True)
            cm = ddf["carrier"].value_counts()
            fig = go.Figure(go.Pie(
                labels=cm.index.tolist(), values=cm.values.tolist(), hole=0.62,
                marker=dict(line=dict(color=PALETTE["surface"], width=2)),
                textinfo="percent",
                hovertemplate="%{label}<br>%{value} (%{percent})<extra></extra>"))
            fig.update_layout(annotations=[dict(
                text=f"<b style='color:#F4F4F5'>{len(ddf):,}</b><br>"
                     "<span style='font-size:10px;color:#A1A1AA'>deliveries</span>",
                x=0.5, y=0.5, showarrow=False, font=dict(size=18))])
            st.plotly_chart(style_fig(fig, height=300), use_container_width=True)

        # ---- Lead time by shift + daily completed ----
        d3, d4 = st.columns(2)
        with d3:
            st.markdown(
                "<div class='sec'><h3>Median delivery time by order shift</h3>"
                "<div class='sec-sub'>Does the evening rush slow fulfilment?</div></div>",
                unsafe_allow_html=True)
            sh_present = ([sh for sh in SHIFT_ORDER
                           if not done_d[done_d["shift"] == sh]["lead_hours"]
                           .dropna().empty] if not done_d.empty else [])
            if sh_present:
                meds = [_median(done_d[done_d["shift"] == sh]["lead_hours"]
                                .dropna().tolist()) for sh in sh_present]
                fig = go.Figure(go.Bar(
                    x=[s.split(" ·")[0] for s in sh_present], y=meds,
                    marker=dict(color=[SHIFT_COLORS[s] for s in sh_present]),
                    text=[_fmt_h(v) for v in meds],
                    textposition="outside",
                    textfont=dict(color=PALETTE["text_dim"], size=10),
                    cliponaxis=False,
                    hovertemplate="%{x}<br>median %{y:.1f} h<extra></extra>"))
                st.plotly_chart(style_fig(fig, height=300, show_legend=False),
                                use_container_width=True)
            else:
                st.info("No data.")
        with d4:
            st.markdown(
                "<div class='sec'><h3>Deliveries completed · daily</h3>"
                "<div class='sec-sub'>Across the period</div></div>",
                unsafe_allow_html=True)
            if not done_d.empty:
                dd_daily = [int((done_d["day"] == d).sum()) for d in days]
                fig = go.Figure(go.Bar(
                    x=day_labels, y=dd_daily,
                    marker=dict(color=PALETTE["sky"]),
                    text=[v if (v and show_day_labels) else "" for v in dd_daily],
                    texttemplate="%{text}", textposition="outside",
                    textfont=dict(color=PALETTE["text_dim"], size=10),
                    cliponaxis=False,
                    hovertemplate="%{x}<br>%{y} delivered<extra></extra>"))
                st.plotly_chart(style_fig(fig, height=300, show_legend=False),
                                use_container_width=True)
            else:
                st.info("No data.")

        # ============ FLEET CAPACITY — do you need another car? ============
        st.markdown(
            "<div class='sec' style='margin-top:20px'><h3>Fleet capacity · do you "
            "need another delivery car?</h3><div class='sec-sub'>Set the three "
            "inputs to match your operation — the verdict recalculates live</div></div>",
            unsafe_allow_html=True)
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            cars_now = st.number_input(
                "Delivery cars available now", min_value=1, max_value=50,
                value=3, step=1, key="fleet_cars")
        with fc2:
            rt_min = st.number_input(
                "Round-trip minutes per delivery", min_value=10, max_value=240,
                value=40, step=5, key="fleet_rt",
                help="How long one car is tied up per run: drive out + hand over + return")
        with fc3:
            batch = st.number_input(
                "Orders carried per trip", min_value=1, max_value=10,
                value=3, step=1, key="fleet_batch",
                help="How many deliveries a driver takes on a single run. "
                     "Most multi-drop operations carry 3-5; set 1 if each run is a single order.")

        # Demand from completion times within the current filters
        dd2 = (done_d.dropna(subset=["done_hour", "done_day"])
               if not done_d.empty else done_d)
        active_days = dd2["done_day"].nunique() if not dd2.empty else 0
        if active_days and not dd2.empty:
            daily_peak = dd2.groupby("done_day")["done_hour"].apply(
                lambda s: int(s.value_counts().max()))
            typical_peak = float(daily_peak.mean())
            worst_peak = int(daily_peak.max())
            avg_per_day = len(dd2) / active_days
        else:
            typical_peak = worst_peak = avg_per_day = 0

        per_car_cap = (60.0 / rt_min) * batch          # deliveries / hour / car
        fleet_cap = cars_now * per_car_cap
        req_typical = math.ceil(typical_peak / per_car_cap) if per_car_cap else 0
        req_worst = math.ceil(worst_peak / per_car_cap) if per_car_cap else 0
        util_typical = (typical_peak / fleet_cap * 100) if fleet_cap else 0

        if req_typical <= cars_now and req_worst <= cars_now:
            verdict = (f"Your <b>{cars_now}</b> car(s) cover both the typical evening "
                       f"peak (~{typical_peak:.0f}/hr) and the busiest hours seen "
                       f"({worst_peak}/hr). No extra car needed — peak utilisation "
                       f"is {util_typical:.0f}%.")
            vcolor = "#22C55E"
        elif req_typical <= cars_now:
            verdict = (f"Your <b>{cars_now}</b> car(s) handle the typical peak "
                       f"(~{typical_peak:.0f}/hr, {util_typical:.0f}% utilised) but "
                       f"fall short on the busiest hours ({worst_peak}/hr needs "
                       f"{req_worst}). Consider <b>1 on-call car</b> for peak evenings "
                       "rather than a permanent addition.")
            vcolor = "#F5B544"
        else:
            verdict = (f"Your <b>{cars_now}</b> car(s) are below the typical peak of "
                       f"~{typical_peak:.0f}/hr, which needs <b>{req_typical}</b> cars. "
                       f"Add <b>{max(0, req_typical - cars_now)}</b> to keep up at peak "
                       f"(up to {req_worst} on the very busiest hours).")
            vcolor = "#F87171"

        ck = "<div class='kpi-grid' style='margin-top:6px'>"
        ck += kpi_card("Typical peak demand", f"{typical_peak:.0f}/hr",
                       "avg of each day's busiest hour",
                       f"Busiest seen: {worst_peak}/hr")
        ck += kpi_card("Capacity per car", f"{per_car_cap:.1f}/hr",
                       f"at {rt_min} min · {batch}/trip", "")
        ck += kpi_card("Fleet capacity", f"{fleet_cap:.1f}/hr",
                       f"{cars_now} car(s)",
                       f"Peak utilisation: {util_typical:.0f}%")
        ck += kpi_card("Cars needed at peak", f"{req_typical}",
                       "for the typical peak",
                       f"Busiest hours: {req_worst}")
        ck += "</div>"
        st.markdown(ck, unsafe_allow_html=True)

        st.markdown(
            f"<div class='insight-card' style='border-color:{vcolor}55'>"
            f"<div class='insight-title' style='color:{vcolor}'>◆ Verdict</div>"
            f"<div style='color:#E4E4E7;font-size:13.5px;line-height:1.7'>{verdict}"
            "</div></div>", unsafe_allow_html=True)

        st.markdown(
            "<div class='sec' style='margin-top:14px'><h3>Hourly delivery demand vs "
            "fleet capacity</h3><div class='sec-sub'>Avg deliveries completed per "
            "hour on an active day; bars above the line exceed current capacity</div></div>",
            unsafe_allow_html=True)
        if active_days and not dd2.empty:
            hours = list(range(24))
            prof = (dd2.groupby("done_hour").size().reindex(hours, fill_value=0)
                    / active_days)
            bar_colors = [("#F87171" if prof[h] > fleet_cap else PALETTE["neon"])
                          for h in hours]
            fig = go.Figure(go.Bar(
                x=[f"{h:02d}" for h in hours], y=prof.values,
                marker=dict(color=bar_colors),
                hovertemplate="%{x}:00<br>%{y:.1f} deliveries/hr<extra></extra>"))
            fig.add_hline(
                y=fleet_cap, line=dict(color="#A78BFA", width=2, dash="dash"),
                annotation_text=f"capacity {fleet_cap:.1f}/hr",
                annotation_position="top left",
                annotation_font_color="#A78BFA")
            st.plotly_chart(style_fig(fig, height=320, show_legend=False),
                            use_container_width=True)
        else:
            st.info("No completed deliveries to model.")


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
    elif scope == "MTD":
        pace_start = today_local.replace(day=1)
        next_m = (pace_start.replace(day=28) + timedelta(days=5)).replace(day=1)
        pace_end = next_m - timedelta(days=1)
        pace_label = "MTD"
        pct_elapsed = ((today_local - pace_start).days + 1) / ((pace_end - pace_start).days + 1)
    elif scope == "YTD":
        pace_start = date(today_local.year, 1, 1)
        pace_end = date(today_local.year, 12, 31)
        pace_label = "Year to Date"
        pct_elapsed = ((today_local - pace_start).days + 1) / 366
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
        _max_p_rev = tbl[f"Revenue ({CURRENCY})"].max() or 1
        _max_p_pro = tbl[f"Profit ({CURRENCY})"].max() or 1
        st.dataframe(
            tbl, use_container_width=True, hide_index=True,
            column_config={
                f"Revenue ({CURRENCY})": st.column_config.ProgressColumn(
                    f"Revenue ({CURRENCY})", format="%,.0f",
                    min_value=0, max_value=float(_max_p_rev)),
                f"Profit ({CURRENCY})": st.column_config.ProgressColumn(
                    f"Profit ({CURRENCY})", format="%,.0f",
                    min_value=0, max_value=float(_max_p_pro)),
                "Margin %": st.column_config.ProgressColumn(
                    "Margin %", format="%.1f%%",
                    min_value=0, max_value=100),
                "% of revenue": st.column_config.ProgressColumn(
                    "% of revenue", format="%.1f%%",
                    min_value=0, max_value=100),
                "% of profit": st.column_config.ProgressColumn(
                    "% of profit", format="%.1f%%",
                    min_value=0, max_value=100),
                "Orders": st.column_config.NumberColumn(format="%,d"),
            },
        )

        # ---- Top profit drivers (customers & salespeople) — leaderboard style ----
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
            top_c = top_c.sort_values("prof", ascending=False).head(10)
            _rows_c = []
            for _, r in top_c.iterrows():
                _rows_c.append({
                    "name": r["customer"],
                    "sub": f"{r['gm_pct']:.1f}% margin",
                    "value": float(r["prof"]),
                    "value_str": fmt_money(r["prof"], CURRENCY, compact=True),
                })
            st.markdown(render_leaderboard(_rows_c), unsafe_allow_html=True)
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
            top_s = top_s.sort_values("prof", ascending=False).head(10)
            _rows_s = []
            for _, r in top_s.iterrows():
                _rows_s.append({
                    "name": r["salesperson"],
                    "sub": f"{r['gm_pct']:.1f}% margin",
                    "value": float(r["prof"]),
                    "value_str": fmt_money(r["prof"], CURRENCY, compact=True),
                })
            st.markdown(render_leaderboard(_rows_s), unsafe_allow_html=True)


# -------- Profit & Loss Statement --------
def _pnl_category_of(name, code):
    """Bucket an Odoo expense account into a P&L category."""
    n = (name or "").lower()
    # Many accounts use 'Parent:Child' naming — take the parent as the bucket.
    parent = n.split(":")[0].strip()
    if parent:
        return parent.title()
    return name or "Other"


with tab_pnl:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='sec'><h3>Profit &amp; Loss Statement</h3>"
        f"<div class='sec-sub'>{scope_label} · "
        "live from Odoo GL · OpEx figures reflect everything posted to "
        "expense accounts company-wide</div></div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "<span style='color:#71717A;font-size:11px'>"
        "Revenue, COGS, and Gross Profit are channel-filtered. "
        "OpEx categories are <b>company-wide</b> (not channel-attributable). "
        "Lines with zero balance are hidden."
        "</span>",
        unsafe_allow_html=True,
    )

    # --- Date strings (account.move.line.date is a Date field — YYYY-MM-DD) ---
    _pnl_curr_start_iso = curr_start.strftime("%Y-%m-%d")
    _pnl_curr_end_iso = curr_end.strftime("%Y-%m-%d")
    _pnl_prev_start_iso = prev_start.strftime("%Y-%m-%d")
    _pnl_prev_end_iso = prev_end.strftime("%Y-%m-%d")

    # --- Revenue & COGS (from existing channel-filtered df) ---
    pnl_rev_curr = float(df_curr["amount_total"].sum()) if not df_curr.empty else 0.0
    pnl_rev_prev = float(df_prev["amount_total"].sum()) if not df_prev.empty else 0.0
    pnl_gp_curr = (float(df_curr["margin"].sum())
                   if not df_curr.empty and "margin" in df_curr.columns else 0.0)
    pnl_gp_prev = (float(df_prev["margin"].sum())
                   if not df_prev.empty and "margin" in df_prev.columns else 0.0)
    pnl_cogs_curr = pnl_rev_curr - pnl_gp_curr
    pnl_cogs_prev = pnl_rev_prev - pnl_gp_prev

    # --- Fetch expense balances from Odoo GL ---
    with st.spinner("Loading expense ledger..."):
        exp_curr = fetch_expense_balances(_pnl_curr_start_iso, _pnl_curr_end_iso, hist_bucket)
        exp_prev = fetch_expense_balances(_pnl_prev_start_iso, _pnl_prev_end_iso, hist_bucket)

    # Build {category -> total balance} from the GL. We INTENTIONALLY skip
    # accounts whose name looks like a 'Cost of Goods Sold' variant — those
    # are already captured by margin-based COGS on the Revenue half.
    def _is_cogs_account(name):
        n = (name or "").lower()
        return "cost of goods sold" in n or "cogs" in n

    def _group_opex(rows):
        from collections import defaultdict
        groups = defaultdict(float)
        for r in rows:
            if _is_cogs_account(r["name"]):
                continue
            if r["type"] == "expense_direct_cost":
                continue  # COGS-flavoured, skip
            if abs(r["balance"]) < 0.01:
                continue
            cat = _pnl_category_of(r["name"], r["code"])
            groups[cat] += r["balance"]
        return dict(groups)

    def _depreciation_total(rows):
        # Pull anything tagged 'expense_depreciation'
        return sum(r["balance"] for r in rows
                   if r["type"] == "expense_depreciation"
                   and abs(r["balance"]) > 0.01)

    opex_curr = _group_opex(exp_curr)
    opex_prev = _group_opex(exp_prev)
    dep_curr = _depreciation_total(exp_curr)
    dep_prev = _depreciation_total(exp_prev)

    total_opex_curr = sum(opex_curr.values())
    total_opex_prev = sum(opex_prev.values())
    ebitda_curr = pnl_gp_curr - total_opex_curr
    ebitda_prev = pnl_gp_prev - total_opex_prev
    ebit_curr = ebitda_curr - dep_curr
    ebit_prev = ebitda_prev - dep_prev

    def _gm_pct(profit, rev):
        return (profit / rev * 100) if rev else 0.0

    def _pct_delta(c, p):
        if not p:
            return None
        return (c - p) / p * 100

    def _fmt_num(x):
        return f"{x:,.0f}"

    def _fmt_delta(c, p, unit="%"):
        d = _pct_delta(c, p)
        if d is None:
            return "<span style='color:#71717A'>—</span>"
        cls = "kpi-delta-up" if d >= 0 else "kpi-delta-dn"
        sign = "▲" if d >= 0 else "▼"
        return (f"<span class='{cls}'>{sign} {abs(d):.1f}%</span>")

    # --- Render P&L table as styled HTML ---
    css_seed = """
    <style>
    .pnl-table {
        width: 100%;
        border-collapse: collapse;
        font-variant-numeric: tabular-nums;
        margin-top: 14px;
        background: linear-gradient(160deg, #131318 0%, #0E0E13 100%);
        border: 1px solid #23232B;
        border-radius: 14px;
        overflow: hidden;
    }
    .pnl-table th, .pnl-table td {
        padding: 11px 18px;
        text-align: right;
        color: #D4D4D8;
        font-size: 13px;
        border-bottom: 1px solid #1A1A20;
    }
    .pnl-table th { color: #71717A; text-transform: uppercase;
                    letter-spacing: 0.12em; font-size: 10.5px;
                    font-weight: 700; background: #16161B;
                    border-bottom: 1px solid #23232B; }
    .pnl-table th:first-child, .pnl-table td:first-child {
        text-align: left;
    }
    .pnl-row-label { color: #F4F4F5; }
    .pnl-sub-label { color: #A1A1AA; padding-left: 24px !important; font-weight: 400; }
    .pnl-total {
        background: rgba(25,227,182,0.04);
        font-weight: 700;
    }
    .pnl-total td { color: #F4F4F5 !important; border-top: 1px solid #2A2A33; }
    .pnl-bottom {
        background: rgba(25,227,182,0.10);
    }
    .pnl-bottom td { color: #19E3B6 !important; font-weight: 800; font-size: 15px; }
    .pnl-neg { color: #F87171; }
    </style>
    """
    st.markdown(css_seed, unsafe_allow_html=True)

    def _row(label, c_val, p_val, *, is_neg=False, css_class="", sub=False):
        delta = _fmt_delta(c_val, p_val) if p_val or c_val else "—"
        label_cls = "pnl-sub-label" if sub else "pnl-row-label"
        c_str = f"({_fmt_num(abs(c_val))})" if is_neg else _fmt_num(c_val)
        p_str = f"({_fmt_num(abs(p_val))})" if is_neg else _fmt_num(p_val)
        neg_cls = "pnl-neg" if is_neg else ""
        return (
            f"<tr class='{css_class}'>"
            f"<td class='{label_cls}'>{label}</td>"
            f"<td class='{neg_cls}'>{c_str}</td>"
            f"<td class='{neg_cls}'>{p_str}</td>"
            f"<td>{delta}</td>"
            f"</tr>"
        )

    table_html = ["<table class='pnl-table'>"]
    table_html.append(
        f"<thead><tr><th>Line Item</th>"
        f"<th>{scope_label} ({CURRENCY})</th>"
        f"<th>Prior period ({CURRENCY})</th>"
        f"<th>Δ %</th></tr></thead><tbody>"
    )
    # Revenue
    table_html.append(_row("Revenue (net of VAT)", pnl_rev_curr, pnl_rev_prev,
                           css_class="pnl-total"))
    table_html.append(_row("Cost of Goods Sold", pnl_cogs_curr, pnl_cogs_prev,
                           is_neg=True))
    # Gross Profit
    table_html.append(_row("Gross Profit", pnl_gp_curr, pnl_gp_prev,
                           css_class="pnl-total"))
    gm_curr = _gm_pct(pnl_gp_curr, pnl_rev_curr)
    gm_prev = _gm_pct(pnl_gp_prev, pnl_rev_prev)
    ppt_delta = gm_curr - gm_prev
    ppt_cls = "kpi-delta-up" if ppt_delta >= 0 else "kpi-delta-dn"
    ppt_sign = "▲" if ppt_delta >= 0 else "▼"
    ppt_html = (f"<span class='{ppt_cls}'>{ppt_sign} {abs(ppt_delta):.1f} ppt</span>"
                if pnl_rev_prev else "<span style='color:#71717A'>—</span>")
    table_html.append(
        f"<tr><td class='pnl-sub-label'><i>Gross Margin %</i></td>"
        f"<td><i>{gm_curr:.1f}%</i></td>"
        f"<td><i>{gm_prev:.1f}%</i></td>"
        f"<td>{ppt_html}</td></tr>"
    )

    # Spacer row
    table_html.append(
        "<tr><td colspan='4' style='height:8px;background:#0E0E13;"
        "border-bottom:1px solid #2A2A33'></td></tr>"
    )
    # Operating Expenses header
    table_html.append(
        "<tr><td class='pnl-row-label' style='color:#A78BFA;"
        "text-transform:uppercase;letter-spacing:0.10em;font-size:11px;"
        "font-weight:700' colspan='4'>Operating Expenses</td></tr>"
    )

    # Sort OpEx categories by absolute current-period spend
    all_cats = sorted(set(list(opex_curr.keys()) + list(opex_prev.keys())),
                      key=lambda c: -abs(opex_curr.get(c, 0)))
    if not all_cats:
        table_html.append(
            "<tr><td colspan='4' class='pnl-sub-label' style='color:#71717A'>"
            "<i>No operating expenses posted to Odoo for this period. "
            "OpEx values will appear here as the accounting team posts them.</i>"
            "</td></tr>"
        )
    for cat in all_cats:
        c_val = opex_curr.get(cat, 0)
        p_val = opex_prev.get(cat, 0)
        table_html.append(_row(cat, c_val, p_val, is_neg=True, sub=True))

    # Total OpEx
    table_html.append(_row("Total OpEx", total_opex_curr, total_opex_prev,
                           is_neg=True, css_class="pnl-total"))

    # EBITDA
    table_html.append(_row("EBITDA", ebitda_curr, ebitda_prev,
                           css_class="pnl-total"))

    # Depreciation
    if abs(dep_curr) > 0.01 or abs(dep_prev) > 0.01:
        table_html.append(_row("Depreciation & Amortisation", dep_curr, dep_prev,
                               is_neg=True, sub=True))

    # EBIT / Net Income (without tax/interest data we approximate as EBIT)
    table_html.append(_row("EBIT (Operating Income)", ebit_curr, ebit_prev,
                           css_class="pnl-bottom"))

    table_html.append("</tbody></table>")
    st.markdown("\n".join(table_html), unsafe_allow_html=True)

    # --- Visual: OpEx breakdown (horizontal bar) ---
    st.markdown(
        "<div class='sec' style='margin-top:18px'><h3>Operating expenses · breakdown</h3>"
        "<div class='sec-sub'>Posted to Odoo this period — top categories</div></div>",
        unsafe_allow_html=True,
    )
    if not opex_curr:
        st.info("No OpEx posted for this period.")
    else:
        op_items = sorted(opex_curr.items(), key=lambda x: -x[1])
        labels = [c for c, _ in op_items]
        values = [v for _, v in op_items]
        fig = go.Figure(go.Bar(
            x=values[::-1], y=labels[::-1], orientation="h",
            marker=dict(color=values[::-1],
                        colorscale=[[0, "#0E5A4A"], [1, "#F87171"]],
                        line=dict(width=0)),
            text=values[::-1], texttemplate="%{text:,.0f}",
            textposition="outside",
            textfont=dict(color=PALETTE["text_dim"], size=10),
            cliponaxis=False,
            hovertemplate="<b>%{y}</b><br>%{x:,.0f} " + CURRENCY + "<extra></extra>",
        ))
        st.plotly_chart(style_fig(fig, height=max(300, len(labels) * 26 + 80),
                                  show_legend=False),
                        use_container_width=True)

    # --- Detailed account-level table (drill-down) ---
    st.markdown(
        "<div class='sec' style='margin-top:18px'><h3>Detailed account ledger</h3>"
        "<div class='sec-sub'>Every expense account with a non-zero balance · sortable</div></div>",
        unsafe_allow_html=True,
    )
    detail_rows = []
    for r in exp_curr:
        if abs(r["balance"]) < 0.01:
            continue
        prev_bal = next((p["balance"] for p in exp_prev if p["id"] == r["id"]), 0)
        detail_rows.append({
            "Code": r["code"],
            "Account": r["name"],
            "Type": r["type"],
            f"Period ({CURRENCY})": r["balance"],
            f"Prior ({CURRENCY})": prev_bal,
            "Δ %": ((r["balance"] - prev_bal) / prev_bal * 100) if prev_bal else None,
        })
    if detail_rows:
        det_df = pd.DataFrame(detail_rows).sort_values(
            f"Period ({CURRENCY})", ascending=False
        )
        _max_pnl_amt = det_df[f"Period ({CURRENCY})"].max() or 1
        st.dataframe(
            det_df, use_container_width=True, hide_index=True, height=420,
            column_config={
                f"Period ({CURRENCY})": st.column_config.ProgressColumn(
                    f"Period ({CURRENCY})", format="%,.0f",
                    min_value=0, max_value=float(_max_pnl_amt)),
                f"Prior ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                "Δ %": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
    else:
        st.caption(
            "<span style='color:#71717A;font-size:11.5px'>"
            "Every expense account is at zero for this period — the GL "
            "doesn't have OpEx postings yet."
            "</span>",
            unsafe_allow_html=True,
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

            # ---- Apply the active channel slicer ----
            # The line fetch is date-only filtered; keep only lines whose
            # (source, order_id) appears in df_curr (channel-filtered).
            if not df_curr.empty:
                _allowed_pairs = set(zip(
                    df_curr["source"].astype(str),
                    df_curr["order_id"].fillna(-1).astype(int),
                ))
                sku_df = sku_df[sku_df.apply(
                    lambda r: (r["source"],
                               int(r["order_id"]) if pd.notna(r["order_id"]) else -1)
                              in _allowed_pairs,
                    axis=1,
                )]

        if sku_rows and sku_df.empty:
            st.info("No product line data for the active channel + period selection.")
        elif sku_rows and not sku_df.empty:
            # ---- Attach category / sub-category to each line ----
            _unique_pids = tuple(sorted({
                int(p) for p in sku_df["product_id"].dropna().tolist()
            }))
            with st.spinner("Resolving product categories..."):
                _cat_map = fetch_product_categories(_unique_pids, hist_bucket)

            def _cat_lookup(pid, key):
                if pid is None or pd.isna(pid):
                    return "—"
                try:
                    return _cat_map.get(int(pid), {}).get(key, "—") or "—"
                except (TypeError, ValueError):
                    return "—"

            sku_df["subcategory"] = sku_df["product_id"].map(
                lambda p: _cat_lookup(p, "subcategory"))
            sku_df["group"] = sku_df["product_id"].map(
                lambda p: _cat_lookup(p, "group"))

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
                        lines=("revenue", "count"),
                        subcategory=("subcategory", "first"),
                        group=("group", "first"))
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
            tbl = tbl[["product_name", "subcategory", "group",
                       "units", "lines", "revenue",
                       "margin", "margin_pct", "share_rev"]]
            tbl.columns = ["Product", "Sub-category", "Group",
                           "Units", "Order lines",
                           f"Revenue ({CURRENCY})", f"Profit ({CURRENCY})",
                           "Margin %", "% of revenue"]
            _max_sku_rev = tbl[f"Revenue ({CURRENCY})"].max() or 1
            _max_sku_units = tbl["Units"].max() or 1
            _max_sku_share = tbl["% of revenue"].max() or 1
            st.dataframe(
                tbl, use_container_width=True, hide_index=True, height=520,
                column_config={
                    "Product": st.column_config.TextColumn(width="large"),
                    "Sub-category": st.column_config.TextColumn(width="medium"),
                    "Group": st.column_config.TextColumn(width="small"),
                    "Units": st.column_config.ProgressColumn(
                        "Units", format="%,.0f",
                        min_value=0, max_value=float(_max_sku_units)),
                    "Order lines": st.column_config.NumberColumn(format="%,d"),
                    f"Revenue ({CURRENCY})": st.column_config.ProgressColumn(
                        f"Revenue ({CURRENCY})", format="%,.0f",
                        min_value=0, max_value=float(_max_sku_rev)),
                    f"Profit ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                    "Margin %": st.column_config.ProgressColumn(
                        "Margin %", format="%.1f%%",
                        min_value=0, max_value=100),
                    "% of revenue": st.column_config.ProgressColumn(
                        "% of revenue", format="%.1f%%",
                        min_value=0, max_value=float(_max_sku_share * 1.1)),
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
                cust_loss["Customer"] = cust_loss["Customer"].map(_ltr)
                _max_lc_loss = cust_loss[f"Loss ({CURRENCY})"].max() or 1
                st.dataframe(
                    cust_loss, use_container_width=True, hide_index=True, height=460,
                    column_config={
                        f"Revenue ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                        f"Loss ({CURRENCY})": st.column_config.ProgressColumn(
                            f"Loss ({CURRENCY})", format="%,.0f",
                            min_value=0, max_value=float(_max_lc_loss)),
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
                _max_ls_loss = sp_loss[f"Loss ({CURRENCY})"].max() or 1
                st.dataframe(
                    sp_loss, use_container_width=True, hide_index=True, height=460,
                    column_config={
                        f"Revenue ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                        f"Loss ({CURRENCY})": st.column_config.ProgressColumn(
                            f"Loss ({CURRENCY})", format="%,.0f",
                            min_value=0, max_value=float(_max_ls_loss)),
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
            detail["Customer"] = detail["Customer"].map(_ltr)
            _max_loss = detail[f"Loss ({CURRENCY})"].max() or 1
            st.dataframe(
                detail, use_container_width=True, hide_index=True, height=620,
                column_config={
                    f"Revenue ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                    f"Cost ({CURRENCY})": st.column_config.NumberColumn(format="%,.0f"),
                    f"Loss ({CURRENCY})": st.column_config.ProgressColumn(
                        f"Loss ({CURRENCY})",
                        format="%,.0f",
                        min_value=0, max_value=float(_max_loss),
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
            _max_rev = tbl[f"Revenue ({CURRENCY})"].max() or 1
            st.dataframe(
                tbl, use_container_width=True, hide_index=True,
                column_config={
                    f"Revenue ({CURRENCY})": st.column_config.ProgressColumn(
                        f"Revenue ({CURRENCY})",
                        format="%,.0f",
                        min_value=0,
                        max_value=float(_max_rev),
                    ),
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
            top["Customer"] = top["Customer"].map(_ltr)
            _max_cu_rev = top[f"Revenue ({CURRENCY})"].max() or 1
            st.dataframe(
                top, use_container_width=True, hide_index=True, height=520,
                column_config={f"Revenue ({CURRENCY})":
                               st.column_config.ProgressColumn(
                                   f"Revenue ({CURRENCY})", format="%,.0f",
                                   min_value=0, max_value=float(_max_cu_rev))},
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
            top["Customer"] = top["Customer"].map(_ltr)
            _max_co_orders = top["Orders"].max() or 1
            _max_co_rev = top[f"Revenue ({CURRENCY})"].max() or 1
            st.dataframe(
                top, use_container_width=True, hide_index=True, height=520,
                column_config={
                    f"Revenue ({CURRENCY})": st.column_config.ProgressColumn(
                        f"Revenue ({CURRENCY})", format="%,.0f",
                        min_value=0, max_value=float(_max_co_rev)),
                    "Orders": st.column_config.ProgressColumn(
                        "Orders", format="%,d",
                        min_value=0, max_value=float(_max_co_orders)),
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

    # Exclude pseudo-customers that distort cohort math:
    #  - "Walk-in"               (POS orders without a partner_id — lumped bucket)
    #  - "Fyxx Operations (B2C)" (company self-purchase / internal entries)
    #  - "—"                     (sale.orders without a partner_id)
    _COHORT_EXCLUDE = {
        "Walk-in", "walk-in", "Walk In", "walk in",
        "Fyxx Operations (B2C)", "fyxx operations (b2c)",
        "Fyxx Operations", "fyxx operations",
        "—", "-", "",
    }
    df_cohort_src = (df[~df["customer"].astype(str).str.strip().isin(_COHORT_EXCLUDE)]
                     if not df.empty else df)
    _excluded_n = (len(df) - len(df_cohort_src)) if not df.empty else 0

    if df_cohort_src.empty:
        st.info("No real customer data available after excluding walk-ins "
                "and internal entries.")
    else:
        if _excluded_n > 0:
            st.caption(
                f"<span style='color:#71717A;font-size:11px'>"
                f"Cohort math excludes <b style='color:#A1A1AA'>"
                f"{_excluded_n:,}</b> rows from <i>Walk-in</i> and "
                f"<i>Fyxx Operations (B2C)</i> (anonymous / internal). "
                f"Real customers tracked: "
                f"{df_cohort_src['customer'].nunique():,}."
                f"</span>",
                unsafe_allow_html=True,
            )

        # Compute first-purchase month per customer
        first_order = df_cohort_src.groupby("customer")["dt_local"].min().reset_index()
        first_order["cohort"] = first_order["dt_local"].dt.to_period("M")
        # All orders, tagged with their customer's cohort
        co = df_cohort_src.merge(first_order[["customer", "cohort"]], on="customer", how="left")
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
        # New vs returning revenue in current scope (still excluding walk-ins
        # and internal entries, consistent with the cohort math)
        df_curr_real = df_curr[~df_curr["customer"].astype(str).str.strip()
                                .isin(_COHORT_EXCLUDE)] if not df_curr.empty else df_curr
        if not df_curr_real.empty:
            df_c = df_curr_real.merge(first_order[["customer", "cohort"]],
                                      on="customer", how="left")
            df_c = df_c[df_c["cohort"].notna()]
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
        df_all = df_cohort_src.merge(first_order[["customer", "cohort"]],
                                     on="customer", how="left")
        df_all = df_all[df_all["cohort"].notna()]
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
        ltv = (df_cohort_src.groupby("customer")["amount_total"].sum()
               .sort_values(ascending=False))
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
        show["Customer"] = show["Customer"].map(_ltr)
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
