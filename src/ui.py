"""
ui.py
=====
Credit Desk — design system.

A single place for design tokens, the injected stylesheet, the Plotly theme, and the
small set of reusable components the pages are built from. Pages import from here and
never hand-write colours or markup.

See docs/design_system.md for the reasoning behind these choices.
"""

from __future__ import annotations

import html as _html
from typing import Iterable, Sequence

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# =========================================================================================
# TOKENS
# =========================================================================================
INK = "#1B2430"
INK_SOFT = "#5B6879"
INK_FAINT = "#8A96A6"
BORDER = "#DDE2EA"
BORDER_STRONG = "#C5CDDA"
CANVAS = "#F3F5F8"
SURFACE = "#FFFFFF"

BRAND = "#0B6B62"
BRAND_DEEP = "#07453F"
BRAND_TINT = "#E4F1EF"

LOW = "#1F7A5C"
MED = "#C2721A"
HIGH = "#A32C2C"

RISK_COLORS = {"Low": LOW, "Medium": MED, "High": HIGH}
OUTCOME_COLORS = {"Approved": LOW, "Rejected": HIGH}

RADIUS = "6px"
# Fonts: system fonts only, so the app makes NO request to the internet. The stack ends with
# fonts that carry Khmer glyphs, so Khmer text typed into notes and rationales displays properly.
FONT_STACK = ("'IBM Plex Sans', -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, "
              "'Noto Sans Khmer', 'Khmer UI', 'Leelawadee UI', 'Khmer OS', sans-serif")

# Policy bands for debt-to-income. The single most reused threshold in the app.
DTI_BANDS: list[tuple[float, float, str, str]] = [
    (0.00, 0.20, "Comfortable", LOW),
    (0.20, 0.30, "Standard", "#5E9E7E"),
    (0.30, 0.45, "Stretched", MED),
    (0.45, 0.80, "Over policy", HIGH),
]

# The same four words appear on the rail, in the routing banner, in the batch results and
# in the decision record. One vocabulary, learned once.
PROBABILITY_BANDS: list[tuple[float, float, str, str]] = [
    (0.00, 0.35, "Decline", HIGH),
    (0.35, 0.55, "Refer", MED),
    (0.55, 0.75, "Review", "#5E9E7E"),
    (0.75, 1.001, "Fast-track", LOW),
]


# =========================================================================================
# FORMATTERS
# =========================================================================================
def money(value: float, decimals: int = 1) -> str:
    """Compact currency that never truncates: $980, $119.8K, $1.2M."""
    if value is None or pd.isna(value):
        return "—"
    v = float(value)
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1_000_000_000:
        return f"{sign}${v / 1_000_000_000:.{decimals}f}B"
    if v >= 1_000_000:
        return f"{sign}${v / 1_000_000:.{decimals}f}M"
    if v >= 10_000:
        return f"{sign}${v / 1_000:.{decimals}f}K"
    return f"{sign}${v:,.0f}"


def pct(value: float, decimals: int = 1) -> str:
    """0.529 -> 52.9%  (pass fractions, not percentages)."""
    if value is None or pd.isna(value):
        return "—"
    return f"{value * 100:.{decimals}f}%"


def pp(value: float, decimals: int = 1) -> str:
    """Signed percentage-point delta: +4.2pp / -11.0pp."""
    if value is None or pd.isna(value):
        return "—"
    return f"{value * 100:+.{decimals}f}pp"


def count(value: float) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{int(value):,}"


# =========================================================================================
# STYLESHEET
# =========================================================================================
def _stylesheet() -> str:
    return f"""
<style>
html, body, [class*="st-"], button, input, textarea, select {{
    font-family: {FONT_STACK};
}}

.stApp {{ background: {CANVAS}; }}

.block-container {{
    padding-top: 2.1rem;
    padding-bottom: 4rem;
    max-width: 1360px;
}}

/* ---- Type scale -------------------------------------------------------------- */
h1, h2, h3, h4 {{
    color: {INK};
    letter-spacing: -0.015em;
    font-weight: 600;
}}
h1 {{ font-size: 1.85rem; margin-bottom: 0.15rem; }}
h2 {{ font-size: 1.30rem; margin-top: 2.0rem; margin-bottom: 0.5rem; }}
h3 {{ font-size: 1.02rem; margin-top: 1.4rem; margin-bottom: 0.35rem; }}
p, li, .stMarkdown {{ color: {INK}; font-size: 0.925rem; line-height: 1.62; }}

/* Every figure in the app lines up in its column. */
[data-testid="stMetricValue"], .cd-kpi-value, .cd-num,
[data-testid="stDataFrame"], [data-testid="stTable"] {{
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum";
}}

/*
 * ---- Icon fallback safety net --------------------------------------------------
 * Streamlit draws its built-in glyphs (sidebar collapse arrow, expander chevron,
 * uploader icon, ...) from the Material Symbols web font. On a network that can't
 * reach Google Fonts — as here — the font never arrives and the browser falls back
 * to printing the glyph's raw name ("keyboard_double_arrow_left", "upload") as
 * literal text on top of the label next to it.
 *
 * The fix has two layers: hide that raw text everywhere by default (a missing icon
 * reads far cleaner than a stray word bleeding into a button), then draw a small
 * set of dependency-free icons — plain SVG shapes inlined as data URIs, so they
 * render with zero network access — for the handful of spots worth it.
 */
:root {{
    --cd-icon-chevron-left:
        url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M15 5l-7 7 7 7' fill='none' stroke='black' stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
    --cd-icon-chevron-right:
        url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M9 5l7 7-7 7' fill='none' stroke='black' stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
    --cd-icon-upload:
        url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M12 4v11m0-11 4.5 4.5M12 4 7.5 8.5M5 17v1.8A2.2 2.2 0 0 0 7.2 21h9.6a2.2 2.2 0 0 0 2.2-2.2V17' fill='none' stroke='black' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
}}
span[data-testid="stIconMaterial"] {{
    font-size: 0 !important;
    color: transparent !important;
}}

/* ---- Navigation rail --------------------------------------------------------- */
[data-testid="stSidebar"] {{
    background: {BRAND_DEEP};
    border-right: 1px solid {BRAND_DEEP};
    width: 268px !important;
}}
[data-testid="stSidebar"] > div:first-child {{ padding-top: 0.75rem; }}
[data-testid="stSidebar"] * {{ color: #DCE9E7; }}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {{ color: #FFFFFF; }}

/* Section captions in the nav */
[data-testid="stSidebarNav"] {{
    padding-top: 0;
}}

/*
 * ---- Sidebar header: collapse control + brand, as one row ---------------------
 * Streamlit reserves a header strip above the nav for its collapse toggle. Putting
 * the brand name in that same strip (via ::after, so it costs no extra DOM) reads
 * as one deliberate header instead of a stray button floating above the title.
 */
[data-testid="stSidebarHeader"] {{
    display: flex;
    align-items: center;
    gap: 0.65rem;
    min-height: unset;
    height: auto;
    padding: 0.7rem 0.85rem;
    border-bottom: 1px solid rgba(255,255,255,0.13);
    margin-bottom: 0.5rem;
}}
[data-testid="stSidebarHeader"]::after {{
    content: "Credit Desk";
    color: #FFFFFF;
    font-size: 1.04rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    white-space: nowrap;
}}
[data-testid="stSidebarHeader"] button {{
    background: rgba(255,255,255,0.14) !important;
    border: 1px solid rgba(255,255,255,0.45) !important;
    border-radius: 5px;
    width: 2.3rem;
    height: 2.3rem;
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    justify-content: center;
}}
[data-testid="stSidebarHeader"] button:hover {{
    background: rgba(255,255,255,0.24) !important;
    border-color: #6FD3C4 !important;
}}
[data-testid="stSidebarHeader"] span[data-testid="stIconMaterial"] {{
    width: 1.05rem;
    height: 1.05rem;
    display: inline-block;
    position: relative;
}}
[data-testid="stSidebarHeader"] span[data-testid="stIconMaterial"]::before {{
    content: "";
    position: absolute;
    inset: 0;
    background-color: #FFFFFF;
    -webkit-mask: var(--cd-icon-chevron-left) center / contain no-repeat;
    mask: var(--cd-icon-chevron-left) center / contain no-repeat;
}}

/*
 * The floating re-open control shown in the main pane once the rail is collapsed —
 * this is the ONLY way back into the app's navigation and filters, so it needs to
 * read as a button on sight, not as a stray mark in the corner. A visible pill with
 * a chevron plus the word "Menu" (plain text, not an icon font, so it can't vanish
 * if a web-font fails to load) does that regardless of Streamlit version or theme.
 */
[data-testid="stSidebarCollapsedControl"] {{
    background: {BRAND_DEEP} !important;
    border: 1px solid #6FD3C4 !important;
    border-radius: 0 8px 8px 0 !important;
    box-shadow: 1px 2px 8px rgba(0,0,0,0.28);
    display: flex !important;
    align-items: center;
    min-height: 2.3rem;
    padding-right: 0.65rem !important;
}}
[data-testid="stSidebarCollapsedControl"]::after {{
    content: "Menu";
    color: #FFFFFF;
    font-family: {FONT_STACK};
    font-size: 0.76rem;
    font-weight: 700;
    letter-spacing: 0.02em;
    padding-left: 0.15rem;
    pointer-events: none;
}}
[data-testid="stSidebarCollapsedControl"] span[data-testid="stIconMaterial"] {{
    width: 1.05rem;
    height: 1.05rem;
    display: inline-block;
    position: relative;
}}
[data-testid="stSidebarCollapsedControl"] span[data-testid="stIconMaterial"]::before {{
    content: "";
    position: absolute;
    inset: 0;
    background-color: #FFFFFF;
    -webkit-mask: var(--cd-icon-chevron-right) center / contain no-repeat;
    mask: var(--cd-icon-chevron-right) center / contain no-repeat;
}}

/*
 * ---- Collapsible nav groups (Portfolio / Decisioning / Governance) ------------
 * Each section header is a real button (see app.py:render_nav) carrying a plain
 * ▾ / ▸ text arrow — no icon font involved, so the "click here to expand" signal
 * can never disappear the way a web-font icon can.
 */
[class*="st-key-navgrp_"] .stButton button {{
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    justify-content: flex-start !important;
    color: #BFDCD7 !important;
    font-size: 0.76rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.01em;
    padding: 0.7rem 0.75rem 0.3rem 0.75rem !important;
}}
[class*="st-key-navgrp_"] .stButton button:hover {{
    color: #FFFFFF !important;
    background: transparent !important;
}}
[data-testid="stSidebar"] [data-testid="stPageLink"] {{
    border-radius: 4px;
    margin: 1px 6px;
    padding: 0.32rem 0.6rem 0.32rem 1.35rem !important;
}}
[data-testid="stSidebar"] [data-testid="stPageLink"] p {{
    font-size: 0.895rem !important; font-weight: 450;
}}
[data-testid="stSidebar"] [data-testid="stPageLink"]:hover {{
    background: rgba(255,255,255,0.07);
}}
[data-testid="stSidebar"] [data-testid="stPageLink"][aria-current="page"] {{
    background: rgba(255,255,255,0.13);
    box-shadow: inset 2px 0 0 0 #6FD3C4;
}}
[data-testid="stSidebar"] [data-testid="stPageLink"][aria-current="page"] p {{
    font-weight: 600; color: #FFFFFF !important;
}}

[data-testid="stSidebarNav"] ul {{ padding-top: 0.2rem; }}
[data-testid="stSidebarNav"] a {{
    border-radius: 4px;
    margin: 1px 6px;
    padding: 0.32rem 0.6rem !important;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}}
[data-testid="stSidebarNav"] a span {{ font-size: 0.895rem; font-weight: 450; }}

/* We ship no page icons in the nav, so the global icon-fallback rule above already
   keeps any stray icon span from ever showing raw glyph-name text here. */
[data-testid="stSidebarNav"] span[data-testid="stIconMaterial"] {{
    display: none;
}}
[data-testid="stSidebarNav"] a:hover {{ background: rgba(255,255,255,0.07); }}
[data-testid="stSidebarNav"] a[aria-current="page"] {{
    background: rgba(255,255,255,0.13);
    box-shadow: inset 2px 0 0 0 #6FD3C4;
}}
[data-testid="stSidebarNav"] a[aria-current="page"] span {{ font-weight: 600; color: #FFFFFF; }}

/* ---- Form fields in the main area: a clear outlined white box, so every place to type or
   choose is obvious. Focus turns the outline brand-green. ------------------------------------ */
[data-testid="stMain"] [data-testid="stTextInputRootElement"],
[data-testid="stMain"] [data-testid="stNumberInputContainer"],
[data-testid="stMain"] [data-testid="stTextAreaRootElement"],
[data-testid="stMain"] [data-testid="stDateInputField"],
[data-testid="stMain"] [data-testid="stSelectbox"] .react-aria-ComboBox > div,
[data-testid="stMain"] [data-testid="stMultiSelect"] .react-aria-ComboBox > div,
[data-testid="stMain"] [data-baseweb="input"],
[data-testid="stMain"] [data-baseweb="textarea"],
[data-testid="stMain"] [data-baseweb="select"] > div {{
    background: #FFFFFF !important;
    border: 1.5px solid #8A96A6 !important;
    border-radius: 6px !important;
    box-shadow: none;
}}
/* no double outline where an outlined box sits inside another */
[data-testid="stMain"] [data-testid="stNumberInputContainer"] [data-baseweb="input"],
[data-testid="stMain"] [data-baseweb="input"] [data-baseweb="input"],
[data-testid="stMain"] [data-baseweb="base-input"] {{
    border: none !important;
    background: #FFFFFF !important;
}}
[data-testid="stMain"] [data-testid="stTextInputRootElement"]:focus-within,
[data-testid="stMain"] [data-testid="stNumberInputContainer"]:focus-within,
[data-testid="stMain"] [data-testid="stTextAreaRootElement"]:focus-within,
[data-testid="stMain"] [data-testid="stDateInputField"]:focus-within,
[data-testid="stMain"] [data-testid="stSelectbox"] .react-aria-ComboBox > div:focus-within,
[data-testid="stMain"] [data-testid="stMultiSelect"] .react-aria-ComboBox > div:focus-within,
[data-testid="stMain"] [data-baseweb="input"]:focus-within,
[data-testid="stMain"] [data-baseweb="textarea"]:focus-within,
[data-testid="stMain"] [data-baseweb="select"] > div:focus-within {{
    border-color: {BRAND} !important;
    box-shadow: 0 0 0 3px rgba(11,107,98,0.18) !important;
}}
[data-testid="stMain"] input, [data-testid="stMain"] textarea {{
    color: {INK} !important;
    -webkit-text-fill-color: {INK} !important;
}}
[data-testid="stMain"] input::placeholder, [data-testid="stMain"] textarea::placeholder {{
    color: {INK_FAINT} !important;
    -webkit-text-fill-color: {INK_FAINT} !important;
}}
[data-testid="stMain"] input:disabled {{
    color: {INK_SOFT} !important;
    -webkit-text-fill-color: {INK_SOFT} !important;
}}
[data-testid="stMain"] [data-testid="stNumberInput"] button {{
    border-left: 1px solid #C5CDDA !important;
}}
[data-testid="stMain"] [data-testid="stFileUploaderDropzone"] {{
    background: #FFFFFF !important;
    border: 2px dashed #8A96A6 !important;
    border-radius: 8px !important;
}}
[data-testid="stMain"] [data-testid="stWidgetLabel"] p {{
    color: {INK} !important;
    font-weight: 600 !important;
}}

/* Sidebar controls read as dark-surface controls */
[data-testid="stSidebar"] [data-baseweb="select"] > div,
[data-testid="stSidebar"] [data-baseweb="input"] > div,
[data-testid="stSidebar"] .stMultiSelect div[data-baseweb="select"] > div {{
    background: rgba(255,255,255,0.07);
    border-color: rgba(255,255,255,0.20);
    color: #EAF3F1;
}}
/* Readable boxes: the sidebar paints every text pale (for the dark background), but select,
   multiselect and date boxes render on a WHITE surface in many browsers/Streamlit versions,
   leaving the chosen value nearly invisible. Make every box white with dark text, always. */
[data-testid="stSidebar"] [data-baseweb="select"] > div,
[data-testid="stSidebar"] [data-baseweb="input"] > div,
[data-testid="stSidebar"] [data-baseweb="base-input"],
[data-testid="stSidebar"] .stDateInput div[data-baseweb="input"] {{
    background: #FFFFFF !important;
    border-color: #C5CDDA !important;
}}
[data-testid="stSidebar"] [data-baseweb="select"] *,
[data-testid="stSidebar"] [data-baseweb="input"] *,
[data-testid="stSidebar"] [data-baseweb="base-input"] *,
[data-testid="stSidebar"] input {{
    color: #1B2430 !important;
    -webkit-text-fill-color: #1B2430 !important;
    opacity: 1 !important;
}}
/* Newer Streamlit date boxes are built from separate day/month/year pieces. */
[data-testid="stSidebar"] [data-testid="stDateInputField"] {{
    background: #FFFFFF !important;
    border-color: #C5CDDA !important;
}}
[data-testid="stSidebar"] [data-testid="stDateInputField"] *,
[data-testid="stSidebar"] [data-testid="stDateInput"] [role="spinbutton"] {{
    font-size: 0.80rem !important;
    letter-spacing: 0 !important;
    color: #1B2430 !important;
    -webkit-text-fill-color: #1B2430 !important;
    opacity: 1 !important;
}}
[data-testid="stSidebar"] [data-testid="stDateInputField"] svg {{
    fill: #5B6879 !important;
    color: #5B6879 !important;
}}
[data-testid="stSidebar"] input::placeholder {{
    color: #5B6879 !important;
    -webkit-text-fill-color: #5B6879 !important;
}}
[data-testid="stSidebar"] [data-baseweb="select"] svg,
[data-testid="stSidebar"] [data-baseweb="input"] svg {{
    fill: #5B6879 !important;
    color: #5B6879 !important;
}}
[data-testid="stSidebar"] [data-baseweb="tag"] {{
    background: #12857A !important;
    border-radius: 3px;
}}
[data-testid="stSidebar"] [data-baseweb="tag"] *,
[data-testid="stSidebar"] [data-baseweb="tag"] svg {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    fill: #FFFFFF !important;
}}
[data-testid="stSidebar"] label p {{
    color: #A8C6C1 !important;
    font-size: 0.78rem !important;
    font-weight: 500;
}}
[data-testid="stSidebar"] .stButton button {{
    background: transparent;
    border: 1px solid rgba(255,255,255,0.26);
    color: #DCE9E7;
    font-size: 0.82rem;
    padding: 0.28rem 0.7rem;
}}
[data-testid="stSidebar"] .stButton button:hover {{
    border-color: #6FD3C4;
    color: #FFFFFF;
    background: rgba(255,255,255,0.06);
}}

.cd-brand {{
    padding: 0.35rem 0.75rem 0.9rem 0.75rem;
    border-bottom: 1px solid rgba(255,255,255,0.13);
    margin-bottom: 0.65rem;
}}
.cd-brand-name {{
    color: #FFFFFF; font-size: 1.04rem; font-weight: 600; letter-spacing: -0.01em;
}}
.cd-brand-sub {{ color: #8FB8B2; font-size: 0.755rem; margin-top: 0.1rem; }}

/* ---- Signed-in user badge, bottom of the sidebar ---------------------------- */
.cd-user {{
    display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem;
    padding: 0.15rem 0.75rem 0.6rem 0.75rem;
}}
.cd-user-name {{ color: #FFFFFF; font-size: 0.86rem; font-weight: 600; }}
.cd-user-role {{
    color: #8FB8B2; font-size: 0.7rem; font-weight: 600; letter-spacing: 0.02em;
    text-transform: uppercase;
}}

/* ---- Login screen -------------------------------------------------------------- */
.cd-login-wrap {{ text-align: center; margin: 4.5rem 0 1.6rem 0; }}
.cd-login-brand {{
    color: {INK}; font-size: 1.9rem; font-weight: 700; letter-spacing: -0.02em;
}}
.cd-login-sub {{ color: {INK_SOFT}; font-size: 0.92rem; margin-top: 0.3rem; }}
[data-testid="stForm"] {{
    border: 1px solid {BORDER}; border-radius: {RADIUS}; background: {SURFACE};
    padding: 1.6rem 1.7rem 1.2rem 1.7rem;
}}

.cd-rail-label {{
    color: #7FA9A3; font-size: 0.72rem; font-weight: 600;
    padding: 0.9rem 0.75rem 0.25rem 0.75rem;
}}

/* ---- Portfolio filter bar (top of Overview / Segments / Drivers / Policy) --------- */
.st-key-cd_filterbar {{
    background: #FFFFFF; border: 1px solid #DCE3E1; border-radius: 12px;
    padding: 0.85rem 1.1rem 0.8rem 1.1rem; margin: 0.35rem 0 1.4rem 0;
    box-shadow: 0 1px 2px rgba(16,24,40,0.04);
}}
.cd-fb-title {{
    color: {BRAND}; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em;
    text-transform: uppercase; margin-bottom: 0.1rem;
}}
.st-key-cd_filterbar [data-testid="stWidgetLabel"] p {{
    font-size: 0.78rem !important; color: {INK_SOFT} !important; font-weight: 600;
}}
.st-key-cd_fb_result {{
    border-top: 1px solid #EEF2F1; padding-top: 0.65rem; margin-top: 0.1rem; row-gap: 0.4rem;
}}
.cd-fb-count {{ margin-right: 0.6rem; line-height: 1.1; white-space: nowrap; }}
.cd-fb-n {{ font-size: 1.55rem; font-weight: 700; color: #14302C; letter-spacing: -0.01em; }}
.cd-fb-of {{ font-size: 0.86rem; color: {INK_SOFT}; }}
.cd-fb-whole {{
    display: inline-block; font-size: 0.8rem; color: {INK_SOFT}; border: 1px dashed #C9D3D1;
    border-radius: 999px; padding: 0.15rem 0.7rem;
}}
.st-key-cd_fb_result .stButton button {{
    background: #E4EFEC; color: #0B5C54; border: 1px solid #C7E0DB; border-radius: 999px;
    font-size: 0.8rem; font-weight: 600; padding: 0.12rem 0.75rem; min-height: 0; line-height: 1.6;
}}
.st-key-cd_fb_result .stButton button p {{ font-size: 0.8rem !important; }}
.st-key-cd_fb_result .stButton button:hover {{
    background: #FDECEA; color: #B42318; border-color: #F4B4AE;
}}
.st-key-cd_chip_clear_all button {{
    background: transparent !important; border: none !important; color: #B42318 !important;
    text-decoration: underline; font-weight: 600;
}}
.st-key-cd_chip_clear_all button:hover {{ background: transparent !important; color: #912018 !important; }}

/* ---- Late-payment alert bar (top of the page) -------------------------------------- */
[class*="st-key-cd_late_banner_"] {{
    border-radius: 10px; padding: 0.8rem 0.9rem 0.95rem 1.1rem; margin: 0 0 1.1rem 0;
}}
/* Red count badge on "Loan book" in the menu */
[data-testid="stSidebar"] .stMarkdownBadge {{
    background-color: #F04438 !important; color: #FFFFFF !important; font-weight: 700;
    font-size: 0.7rem !important; border-radius: 999px; padding: 0.05rem 0.5rem; margin-left: 0.35rem;
}}
.st-key-cd_late_banner_cd-late-red {{
    background: #FEF3F2; border: 1px solid #FECDCA; border-left: 6px solid #B42318;
}}
.st-key-cd_late_banner_cd-late-amber {{
    background: #FFFAEB; border: 1px solid #FEDF89; border-left: 6px solid #B54708;
}}
.cd-late-title {{ font-weight: 700; font-size: 1rem; color: #912018; line-height: 1.35; }}
.st-key-cd_late_banner_cd-late-amber .cd-late-title {{ color: #93370D; }}
.cd-late-body {{ color: #55160C; font-size: 0.88rem; margin-top: 0.15rem; }}
.st-key-cd_late_banner_cd-late-amber .cd-late-body {{ color: #7A2E0E; }}
.cd-late-body b {{ color: #55160C; }}
.cd-late-chips {{ margin-top: 0.4rem; display: flex; flex-wrap: wrap; gap: 0.35rem; }}
.cd-late-chip {{
    display: inline-block; font-size: 0.74rem; font-weight: 600; padding: 0.12rem 0.55rem;
    border-radius: 999px; line-height: 1.4;
}}
[class*="st-key-cd_late_banner_"] [data-testid="stPageLink"] a {{
    background: #B42318; border-radius: 8px; padding: 0.45rem 0.9rem; justify-content: center;
}}
[class*="st-key-cd_late_banner_"] [data-testid="stPageLink"] a p {{
    color: #FFFFFF !important; font-weight: 600; font-size: 0.88rem; white-space: nowrap;
}}
[class*="st-key-cd_late_banner_"] [data-testid="stPageLink"] a:hover {{ background: #912018; }}
[class*="st-key-cd_late_banner_"] .stButton button {{
    background: transparent; border: none; box-shadow: none; color: #912018; min-height: 0;
    padding: 0.2rem 0.4rem;
}}
[class*="st-key-cd_late_banner_"] .stButton button:hover {{ background: rgba(180,35,24,0.08); color: #55160C; }}

/* ---- Page header ------------------------------------------------------------- */
.cd-eyebrow {{ color: {BRAND}; font-size: 0.78rem; font-weight: 600; margin-bottom: 0.1rem; }}
.cd-lede {{ color: {INK_SOFT}; font-size: 0.93rem; max-width: 72ch; margin: 0.15rem 0 0 0; }}
.cd-context {{
    display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem;
    margin: 0.85rem 0 0.2rem 0; padding-bottom: 0.8rem;
    border-bottom: 1px solid {BORDER};
}}
.cd-context-lead {{ color: {INK_SOFT}; font-size: 0.815rem; margin-right: 0.15rem; }}
.cd-chip {{
    display: inline-flex; align-items: center; gap: 0.3rem;
    background: {BRAND_TINT}; color: {BRAND_DEEP};
    border: 1px solid #BFDEDA; border-radius: 3px;
    padding: 0.11rem 0.45rem; font-size: 0.775rem; font-weight: 500;
}}
.cd-chip-key {{ color: {BRAND}; opacity: 0.75; font-weight: 500; }}
.cd-chip-none {{
    background: transparent; color: {INK_FAINT};
    border: 1px dashed {BORDER_STRONG};
}}

/* ---- KPI ---------------------------------------------------------------------- */
.cd-kpi {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: {RADIUS};
    padding: 0.85rem 0.95rem 0.8rem 0.95rem;
    height: 100%;
}}
.cd-kpi-label {{
    color: {INK_SOFT}; font-size: 0.795rem; font-weight: 500;
    display: flex; justify-content: space-between; align-items: baseline; gap: 0.4rem;
}}
.cd-kpi-value {{
    color: {INK}; font-size: 1.72rem; font-weight: 600;
    letter-spacing: -0.025em; line-height: 1.18; margin-top: 0.18rem;
    white-space: nowrap;
}}
/* Long values (model ids, file names) shrink and may wrap instead of spilling out of the box. */
.cd-kpi-value.cd-kpi-long {{
    font-size: 0.92rem; letter-spacing: 0; white-space: normal;
    overflow-wrap: anywhere; word-break: break-word; margin-top: 0.35rem;
}}
.cd-kpi-delta {{ font-size: 0.775rem; font-weight: 600; white-space: nowrap; }}
.cd-kpi-foot {{ color: {INK_FAINT}; font-size: 0.755rem; margin-top: 0.3rem; }}
.cd-up {{ color: {LOW}; }}
.cd-down {{ color: {HIGH}; }}
.cd-flat {{ color: {INK_FAINT}; }}

/* ---- Band rail (signature element) -------------------------------------------- */
.cd-railwrap {{ margin: 0.5rem 0 0.1rem 0; }}
.cd-railtrack {{
    display: flex; height: 6px; width: 100%;
    border-radius: 2px; overflow: hidden; background: {BORDER};
}}
.cd-railseg {{ height: 100%; }}
.cd-railmark {{
    position: relative; height: 11px; margin-top: 2px;
}}
.cd-railmark i {{
    position: absolute; top: 0; width: 2px; height: 9px;
    background: {INK}; transform: translateX(-1px);
    border-radius: 1px;
}}
.cd-railmark i::after {{
    content: ''; position: absolute; top: -9px; left: -3px;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {INK};
}}
.cd-railscale {{
    display: flex; justify-content: space-between;
    color: {INK_FAINT}; font-size: 0.68rem; margin-top: 0.05rem;
}}
.cd-railcap {{
    display: flex; justify-content: space-between; align-items: baseline;
    color: {INK_SOFT}; font-size: 0.755rem; margin-top: 0.1rem;
}}
.cd-railcap b {{ color: {INK}; font-weight: 600; }}

/* ---- Panels, callouts, tags ---------------------------------------------------- */
.cd-panel {{
    background: {SURFACE}; border: 1px solid {BORDER};
    border-radius: {RADIUS}; padding: 1rem 1.15rem;
}}
.cd-note {{
    background: {SURFACE}; border: 1px solid {BORDER};
    border-left: 3px solid {BRAND}; border-radius: 0 {RADIUS} {RADIUS} 0;
    padding: 0.7rem 0.95rem; margin: 0.55rem 0 1.15rem 0;
    color: {INK}; font-size: 0.885rem; line-height: 1.58;
}}
.cd-note.warn {{ border-left-color: {MED}; background: #FDF8F1; }}
.cd-note.stop {{ border-left-color: {HIGH}; background: #FCF4F4; }}
.cd-note b {{ color: {INK}; font-weight: 600; }}
.cd-note-title {{
    display: block; font-weight: 600; color: {INK};
    font-size: 0.85rem; margin-bottom: 0.2rem;
}}

/* ---- Audit trail (short, scannable — a replacement for a raw log dump) --------- */
.cd-audit-list {{
    list-style: none; margin: 0.4rem 0 0 0; padding: 0;
}}
.cd-audit-list li {{
    position: relative; padding: 0.32rem 0 0.32rem 1.15rem;
    color: {INK_SOFT}; font-size: 0.85rem; line-height: 1.5;
    border-bottom: 1px solid {BORDER};
}}
.cd-audit-list li:last-child {{ border-bottom: none; }}
.cd-audit-list li::before {{
    content: "✓"; position: absolute; left: 0; top: 0.3rem;
    color: {LOW}; font-weight: 700; font-size: 0.78rem;
}}

.cd-tag {{
    display: inline-block; border-radius: 3px; padding: 0.06rem 0.42rem;
    font-size: 0.735rem; font-weight: 600; letter-spacing: 0.01em;
}}

/* ---- Decision banner ----------------------------------------------------------- */
.cd-decision {{
    border-radius: {RADIUS}; padding: 1.05rem 1.25rem;
    border: 1px solid {BORDER}; background: {SURFACE};
    display: flex; align-items: center; gap: 1.25rem; flex-wrap: wrap;
}}
.cd-decision-badge {{
    font-size: 1.28rem; font-weight: 700; letter-spacing: -0.02em;
}}
.cd-decision-prob {{
    font-size: 2.45rem; font-weight: 600; letter-spacing: -0.03em;
    line-height: 1; color: {INK};
}}
.cd-decision-sub {{ color: {INK_SOFT}; font-size: 0.83rem; margin-top: 0.15rem; }}

/* ---- Reason codes --------------------------------------------------------------- */
.cd-reason {{
    display: grid; grid-template-columns: 1fr auto;
    gap: 0.35rem 0.8rem; align-items: center;
    padding: 0.5rem 0; border-bottom: 1px solid {BORDER};
}}
.cd-reason:last-child {{ border-bottom: none; }}
.cd-reason-label {{ color: {INK}; font-size: 0.875rem; font-weight: 500; }}
.cd-reason-detail {{ color: {INK_SOFT}; font-size: 0.79rem; }}
.cd-reason-bar {{
    grid-column: 1 / -1; height: 4px; background: {BORDER};
    border-radius: 2px; overflow: hidden;
}}
.cd-reason-bar span {{ display: block; height: 100%; }}

/* ---- Streamlit control restyling -------------------------------------------------- */
div[data-testid="stMetric"] {{
    background: {SURFACE}; border: 1px solid {BORDER};
    border-radius: {RADIUS}; padding: 0.75rem 0.9rem;
}}
[data-testid="stMetricLabel"] p {{ color: {INK_SOFT}; font-size: 0.79rem; font-weight: 500; }}

.stTabs [data-baseweb="tab-list"] {{ gap: 1.4rem; border-bottom: 1px solid {BORDER}; }}
.stTabs [data-baseweb="tab"] {{
    padding: 0.35rem 0; font-size: 0.895rem; font-weight: 500; color: {INK_SOFT};
}}
.stTabs [aria-selected="true"] {{ color: {BRAND} !important; font-weight: 600; }}
.stTabs [data-baseweb="tab-highlight"] {{ background: {BRAND}; height: 2px; }}

.stButton button[kind="primary"], .stFormSubmitButton button[kind="primary"] {{
    background: {BRAND}; border: 1px solid {BRAND};
    font-weight: 600; letter-spacing: 0.005em; border-radius: 5px;
}}
.stButton button[kind="primary"]:hover, .stFormSubmitButton button[kind="primary"]:hover {{
    background: {BRAND_DEEP}; border-color: {BRAND_DEEP};
}}
/* Primary buttons: white text on green, in old and new Streamlit layouts (it was dark grey). */
.stButton button[kind="primary"], .stFormSubmitButton button[kind="primary"],
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {{
    background: {BRAND} !important; border: 1px solid {BRAND} !important; color: #FFFFFF !important;
}}
.stButton button[kind="primary"] *, .stFormSubmitButton button[kind="primary"] *,
[data-testid="stBaseButton-primary"] *, [data-testid="stBaseButton-primaryFormSubmit"] * {{
    color: #FFFFFF !important; font-weight: 600;
}}
[data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover {{
    background: {BRAND_DEEP} !important; border-color: {BRAND_DEEP} !important;
}}
.stButton button[kind="secondary"] {{
    border-radius: 5px; border-color: {BORDER_STRONG}; color: {INK};
}}
[data-testid="stExpander"] {{
    border: 1px solid {BORDER}; border-radius: {RADIUS}; background: {SURFACE};
}}
[data-testid="stExpander"] summary p {{ font-weight: 500; font-size: 0.9rem; }}
[data-testid="stExpander"] summary span[data-testid="stIconMaterial"] {{
    width: 0.85rem; height: 0.85rem; display: inline-block; position: relative;
    transition: transform 0.15s ease;
}}
[data-testid="stExpander"] summary span[data-testid="stIconMaterial"]::before {{
    content: ""; position: absolute; inset: 0; background-color: {INK_SOFT};
    -webkit-mask: var(--cd-icon-chevron-right) center / contain no-repeat;
    mask: var(--cd-icon-chevron-right) center / contain no-repeat;
}}
[data-testid="stExpander"] details[open] summary span[data-testid="stIconMaterial"] {{
    transform: rotate(90deg);
}}

/* File uploader: the drop-zone's own icon glyph is where "upload" was showing up
   twice, doubled over the instruction text. One small, dependency-free glyph
   replaces it. */
[data-testid="stFileUploaderDropzone"] span[data-testid="stIconMaterial"] {{
    display: none;
}}
[data-testid="stFileUploaderDropzoneInstructions"] {{
    display: flex; align-items: center; gap: 0.6rem;
}}
[data-testid="stFileUploaderDropzoneInstructions"]::before {{
    content: ""; flex: 0 0 auto; width: 1.5rem; height: 1.5rem;
    background-color: {INK_FAINT};
    -webkit-mask: var(--cd-icon-upload) center / contain no-repeat;
    mask: var(--cd-icon-upload) center / contain no-repeat;
}}

/* Segmented control / pills pick up the brand */
[data-baseweb="segmented-control"] [aria-checked="true"],
div[data-testid="stSegmentedControl"] button[aria-checked="true"] {{
    background: {BRAND_TINT} !important; color: {BRAND_DEEP} !important;
}}

[data-testid="stDataFrame"] {{ border-radius: {RADIUS}; }}
hr {{ border-color: {BORDER}; margin: 1.6rem 0; }}
footer, #MainMenu {{ visibility: hidden; }}

/* ---- Responsive ------------------------------------------------------------------ */
@media (max-width: 820px) {{
    .cd-kpi-value {{ font-size: 1.42rem; }}
    .block-container {{ padding-top: 1.3rem; }}
    h1 {{ font-size: 1.5rem; }}
}}
@media (prefers-reduced-motion: reduce) {{
    * {{ animation: none !important; transition: none !important; }}
}}
:focus-visible {{ outline: 2px solid {BRAND}; outline-offset: 2px; }}
</style>
"""


def inject_theme() -> None:
    """Install the stylesheet. Call once per rerun, from the app shell."""
    st.markdown(_stylesheet(), unsafe_allow_html=True)


# =========================================================================================
# PLOTLY THEME
# =========================================================================================
def plotly_template() -> go.layout.Template:
    t = go.layout.Template()
    t.layout.colorway = [BRAND, MED, "#4E7CA1", LOW, HIGH, "#8E6FB0"]
    t.layout.font = dict(family=FONT_STACK, color=INK, size=12.5)
    t.layout.paper_bgcolor = SURFACE
    t.layout.plot_bgcolor = SURFACE
    t.layout.margin = dict(l=54, r=22, t=46, b=48)
    t.layout.title = dict(
        font=dict(size=14, color=INK, weight=600), x=0, xanchor="left", y=0.96
    )
    t.layout.xaxis = dict(
        gridcolor="#EEF1F5", linecolor=BORDER, zerolinecolor=BORDER,
        ticks="outside", tickcolor=BORDER, ticklen=4,
        title=dict(font=dict(size=11.5, color=INK_SOFT)),
    )
    t.layout.yaxis = dict(
        gridcolor="#EEF1F5", linecolor=BORDER, zerolinecolor=BORDER,
        title=dict(font=dict(size=11.5, color=INK_SOFT)),
    )
    t.layout.legend = dict(
        orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
        font=dict(size=11.5), title=dict(text=""),
    )
    t.layout.hoverlabel = dict(
        bgcolor=INK, font=dict(family=FONT_STACK, color="#FFFFFF", size=12),
        bordercolor=INK,
    )
    return t


TEMPLATE = plotly_template()


def _width_kwargs() -> dict:
    """
    Streamlit replaced `use_container_width=True` with `width="stretch"` in 1.49 and now
    warns on the old form. Detect which one this install wants, once, so the app is silent
    on both old and new versions rather than printing deprecation notices at a user.
    """
    try:
        import inspect

        params = inspect.signature(st.dataframe).parameters
        if "width" in params:
            return {"width": "stretch"}
    except Exception:
        pass
    return {"use_container_width": True}


STRETCH = _width_kwargs()


def chart(fig: go.Figure, height: int | None = None) -> None:
    """Render a figure with house defaults and the toolbar stripped back."""
    if height:
        fig.update_layout(height=height)
    fig.update_layout(template=TEMPLATE)
    st.plotly_chart(fig, config={"displayModeBar": False, "responsive": True}, **STRETCH)


def table(data, height: int | None = None, **kwargs) -> None:
    """A dataframe or styler, sized to the container on any Streamlit version."""
    extra = {"height": height} if height else {}
    st.dataframe(data, hide_index=kwargs.pop("hide_index", True), **STRETCH,
                 **extra, **kwargs)


# =========================================================================================
# COMPONENTS
# =========================================================================================
def choice(label: str, options: Sequence[str], default: str, key: str) -> str:
    """
    A single-select switch. Uses `st.segmented_control` where available (Streamlit 1.40+)
    and falls back to a horizontal radio so the app still runs on older installs.
    """
    if hasattr(st, "segmented_control"):
        picked = st.segmented_control(
            label, list(options), default=default, key=key, label_visibility="collapsed"
        )
        return picked or default
    idx = list(options).index(default) if default in options else 0
    return st.radio(label, list(options), index=idx, key=key,
                    horizontal=True, label_visibility="collapsed")


def page_header(title: str, lede: str, eyebrow: str | None = None) -> None:
    parts = []
    if eyebrow:
        parts.append(f'<div class="cd-eyebrow">{_html.escape(eyebrow)}</div>')
    parts.append(f"<h1>{_html.escape(title)}</h1>")
    parts.append(f'<p class="cd-lede">{lede}</p>')
    st.markdown("".join(parts), unsafe_allow_html=True)


def context_bar(lead: str, chips: Sequence[tuple[str, str]]) -> None:
    """The live 'what am I looking at' line beneath every page title."""
    out = [f'<div class="cd-context"><span class="cd-context-lead">{lead}</span>']
    if not chips:
        out.append('<span class="cd-chip cd-chip-none">whole book</span>')
    for key, value in chips:
        out.append(
            f'<span class="cd-chip"><span class="cd-chip-key">{_html.escape(key)}</span>'
            f"{_html.escape(value)}</span>"
        )
    out.append("</div>")
    st.markdown("".join(out), unsafe_allow_html=True)


def band_rail(
    value: float,
    bands: Sequence[tuple[float, float, str, str]],
    caption: str | None = None,
    show_scale: bool = True,
) -> str:
    """
    The signature component: policy bands as a segmented rail, with a marker for where
    this value actually sits. Returns HTML so it can be embedded inside other components.
    """
    lo = bands[0][0]
    hi = bands[-1][1]
    span = hi - lo if hi > lo else 1.0

    segs = "".join(
        f'<span class="cd-railseg" style="width:{(b - a) / span * 100:.4f}%;'
        f'background:{color};" title="{_html.escape(label)}"></span>'
        for a, b, label, color in bands
    )

    clamped = min(max(float(value), lo), hi)
    pos = (clamped - lo) / span * 100

    scale = ""
    if show_scale:
        edges = [bands[0][0]] + [b[1] for b in bands]
        ticks = "".join(f"<span>{e * 100:.0f}%</span>" for e in edges)
        scale = f'<div class="cd-railscale">{ticks}</div>'

    cap = f'<div class="cd-railcap">{caption}</div>' if caption else ""

    return (
        f'<div class="cd-railwrap">'
        f'<div class="cd-railtrack">{segs}</div>'
        f'<div class="cd-railmark"><i style="left:{pos:.4f}%"></i></div>'
        f"{scale}{cap}</div>"
    )


def band_label(value: float, bands: Sequence[tuple[float, float, str, str]]) -> tuple[str, str]:
    """Which policy band does this value land in? Returns (label, colour)."""
    for a, b, label, color in bands:
        if a <= value < b:
            return label, color
    return bands[-1][2], bands[-1][3]


def kpi(
    label: str,
    value: str,
    delta: str | None = None,
    delta_dir: str = "flat",
    foot: str | None = None,
    rail: str | None = None,
) -> None:
    """
    A KPI that never truncates and always carries context.

    delta_dir: 'up' (good), 'down' (bad), 'flat' (neutral). Direction is about whether
    the movement is *favourable*, not whether the number went up — approval rate rising
    and high-risk share rising are not the same news.
    """
    cls = {"up": "cd-up", "down": "cd-down"}.get(delta_dir, "cd-flat")
    delta_html = f'<span class="cd-kpi-delta {cls}">{_html.escape(delta)}</span>' if delta else ""
    foot_html = f'<div class="cd-kpi-foot">{_html.escape(foot)}</div>' if foot else ""
    st.markdown(
        f'<div class="cd-kpi">'
        f'<div class="cd-kpi-label"><span>{_html.escape(label)}</span>{delta_html}</div>'
        f'<div class="cd-kpi-value{" cd-kpi-long" if len(str(value)) > 10 else ""}">{_html.escape(value)}</div>'
        f"{rail or ''}{foot_html}</div>",
        unsafe_allow_html=True,
    )


def delta_dir(delta: float, good_when_rising: bool = True, tol: float = 1e-9) -> str:
    """
    Map a raw delta onto 'favourable / unfavourable / flat'.

    Rising approval rate is good news; rising high-risk share is not. Colour has to track
    the interpretation, not the arithmetic sign.
    """
    if delta is None or pd.isna(delta) or abs(delta) <= tol:
        return "flat"
    favourable = (delta > 0) if good_when_rising else (delta < 0)
    return "up" if favourable else "down"


def note(body: str, title: str | None = None, tone: str = "info") -> None:
    """A short piece of interpretation. `tone`: info | warn | stop."""
    cls = {"warn": "cd-note warn", "stop": "cd-note stop"}.get(tone, "cd-note")
    head = f'<span class="cd-note-title">{_html.escape(title)}</span>' if title else ""
    st.markdown(f'<div class="{cls}">{head}{body}</div>', unsafe_allow_html=True)


def tag(text: str, color: str) -> str:
    return (
        f'<span class="cd-tag" style="background:{color}1A;color:{color};'
        f'border:1px solid {color}33;">{_html.escape(text)}</span>'
    )


def panel_open(title: str | None = None) -> None:
    st.markdown('<div class="cd-panel">', unsafe_allow_html=True)
    if title:
        st.markdown(f"##### {title}")


def panel_close() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def section(title: str, sub: str | None = None) -> None:
    st.markdown(f"## {title}")
    if sub:
        st.markdown(f'<p class="cd-lede" style="margin-bottom:0.6rem;">{sub}</p>',
                    unsafe_allow_html=True)


def style_table(df: pd.DataFrame, pct_cols: Iterable[str] = (), money_cols: Iterable[str] = ()):
    """Consistent table formatting: percentages, currency, and a brand-tinted heatmap."""
    fmt: dict[str, object] = {}
    for c in pct_cols:
        if c in df.columns:
            fmt[c] = "{:.1f}%"
    for c in money_cols:
        if c in df.columns:
            fmt[c] = "${:,.0f}"
    styler = df.style.format(fmt, na_rep="—")
    valid = [c for c in pct_cols if c in df.columns]
    if valid:
        styler = gradient(styler, cmap="BuGn", subset=valid, vmin=0, vmax=100)
    return styler


def gradient(styler, **kwargs):
    """Colour-shade table cells. Needs matplotlib; without it the table is shown unshaded
    instead of the page failing."""
    from src.deps import has
    return styler.background_gradient(**kwargs) if has("matplotlib") else styler


def disclaimer(compact: bool = False) -> None:
    """The model caveat, written to be read rather than scrolled past."""
    if compact:
        st.markdown(
            f'<p style="color:{INK_FAINT};font-size:0.775rem;margin-top:0.6rem;">'
            "Decision support only. A model score is not an underwriting decision and must be "
            "reviewed by a credit officer alongside the full credit report.</p>",
            unsafe_allow_html=True,
        )
        return
    note(
        "This model is trained on this institution's own historical decisions, so it learns "
        "past practice — including any bias in it. It sees ten application fields, including "
        "credit score and 12-month late payments, but no full bureau report, collateral, "
        "existing liabilities or fraud signal. Use it to "
        "<b>prioritise and explain</b> manual review. Do not use it to approve or decline.",
        title="Scope of this model",
        tone="warn",
    )
