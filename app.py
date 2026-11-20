from __future__ import annotations

from datetime import date, timedelta
from importlib.util import module_from_spec, spec_from_file_location
import logging
from pathlib import Path
import sys
import zlib
from html import escape

import pandas as pd
import plotly.express as px
import streamlit as st

logger = logging.getLogger(__name__)
DATA_ERRORS = (
    OSError, ValueError, TypeError, KeyError, UnicodeError, OverflowError, EOFError, zlib.error,
    pd.errors.ParserError, pd.errors.EmptyDataError,
)


def load_dashboard_data_module():
    """Load the adjacent Stage 10 helper, avoiding project-wide name collisions."""
    module_path = Path(__file__).resolve().with_name("dashboard_data.py")
    module_name = "_floodguard_stage10_dashboard_data"
    existing = sys.modules.get(module_name)
    required_exports = (
        "ALLOWED_STATES", "DISCLAIMER", "MAP_STATUS_COLORS", "boundary_geojson",
        "date_list", "district_history", "geojson_for_state", "map_rows_for_state",
        "map_status", "map_view_for_selection", "map_snapshot",
        "recent_snapshot_rows", "validate_bundle",
    )
    if (
        existing is not None
        and Path(getattr(existing, "__file__", "")).resolve() == module_path
        and all(hasattr(existing, name) for name in required_exports)
    ):
        return existing

    spec = spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Stage 10 dashboard helper at {module_path}")
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    missing = [name for name in required_exports if not hasattr(module, name)]
    if missing:
        raise ImportError(
            f"Stage 10 dashboard helper {module_path} is missing exports: {', '.join(missing)}"
        )
    return module


dashboard_data = load_dashboard_data_module()
ALLOWED_STATES = dashboard_data.ALLOWED_STATES
DISCLAIMER = dashboard_data.DISCLAIMER
MAP_STATUS_COLORS = dashboard_data.MAP_STATUS_COLORS
boundary_geojson = dashboard_data.boundary_geojson
date_list = dashboard_data.date_list
district_history = dashboard_data.district_history
geojson_for_state = dashboard_data.geojson_for_state
map_rows_for_state = dashboard_data.map_rows_for_state
map_status = dashboard_data.map_status
map_view_for_selection = dashboard_data.map_view_for_selection
map_snapshot = dashboard_data.map_snapshot
recent_snapshot_rows = dashboard_data.recent_snapshot_rows
validate_bundle = dashboard_data.validate_bundle

PAGES = ("Dashboard", "Risk Map", "Data & Sources", "About")
WINDOW_COLUMNS = {
    1: "Rainfall_Prev_1d_mm",
    3: "Rainfall_Prev_3d_mm",
    7: "Rainfall_Prev_7d_mm",
    14: "Rainfall_Prev_14d_mm",
    30: "Rainfall_Prev_30d_mm",
}


st.set_page_config(
    page_title="FloodGuard AI | Historical rainfall screening",
    page_icon=":material/water_drop:",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(
    """
    <style>

    :root {
        --fg-ink:#34271f; --fg-brown:#2b1e18; --fg-brown-2:#432a1b;
        --fg-orange:#b85a18; --fg-orange-bright:#d57522; --fg-gold:#dfb13d;
        --fg-green:#657f45; --fg-red:#9f3c20; --fg-paper:#faf6e9; /* warm ivory */
        --fg-paper-deep:#eee6cf; --fg-card:#fffdf7; --fg-line:#dfd4bd;
        --fg-muted:#6f6358; --fg-radius:15px;
        /* Shared design tokens */
        --bg-primary: var(--fg-paper);
        --bg-card: var(--fg-card);
        --sidebar-bg: var(--fg-brown);
        --accent-orange: var(--fg-orange);
        --accent-gold: var(--fg-gold);
        --accent-green: var(--fg-green);
        --text-primary: var(--fg-ink);
        --text-muted: var(--fg-muted);
        --border-card: var(--fg-line);
        --shadow-card: 0 3px 8px rgba(50,31,14,0.06);
    }
      .stApp {background:var(--fg-paper); color:var(--fg-ink);}
      header[data-testid="stHeader"] {background:rgba(245,240,223,.96);}
      [data-testid="stToolbar"] {visibility:hidden;}
      [data-testid="stToolbar"] [data-testid="stExpandSidebarButton"] {visibility:visible; pointer-events:auto;}
      [data-testid="stDecoration"], .stDeployButton {display:none;}
      .block-container {max-width:1740px; padding:1rem 1.25rem 1.6rem;}
      .st-key-mobile_page {display:none!important;}
      [data-testid="stSidebar"] {min-width:15.5rem; max-width:15.5rem;}
      [data-testid="stSidebar"] > div:first-child {background: var(--sidebar-bg);}
      @media (min-width: 1101px) {
        section[data-testid="stSidebar"][data-collapsed="true"] {
          width:0!important; min-width:0!important; max-width:0!important; flex-basis:0!important;
        }
      }
      [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2 {font-family:Georgia,serif;}
      [data-testid="stSidebar"] [data-testid="stCaption"] {color:#ead9c8;}
      [data-testid="stSidebar"] div[role="radiogroup"] label {
        padding:.52rem .65rem; margin:.16rem 0; border-radius:10px;
        transition:background-color .15s ease, color .15s ease, box-shadow .15s ease;}
      [data-testid="stSidebar"] div[role="radiogroup"] input[type="radio"] {accent-color:#f2a247;}
      [data-testid="stSidebar"] div[role="radiogroup"] label:hover {background:rgba(255,248,236,0.10);}
      [data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {
        background:var(--accent-orange); color:#fff8ec;}
      .stApp :is(button,a,input,select,textarea,summary,[role="button"],[role="combobox"],
        [role="checkbox"],[role="radio"],[tabindex]:not([tabindex="-1"])):focus-visible {
        outline:3px solid #f2a247; outline-offset:2px; box-shadow:0 0 0 2px #321f0e;}
      [data-testid="stSidebar"] div[role="radiogroup"] label:has(input:focus-visible) {
        outline:3px solid #f2a247; outline-offset:2px; box-shadow:0 0 0 2px #321f0e;}
      .fg-brand {display:flex; align-items:center; gap:.72rem; font-family:Georgia,serif;
        font-size:1.42rem; font-weight:700; line-height:1.08; letter-spacing:-.02em;}
      .fg-drop {display:grid; place-items:center; width:2.5rem; height:2.5rem; color:#fff8e8;
        background:#ad4f12; border-radius:13px; font-size:1.32rem;}
      .fg-nav-note {color:#ead9c8; font-size:.8rem; line-height:1.45; margin:.62rem 0 1.1rem;}
      .fg-sidebar-foot {border-top:1px solid #594335; margin-top:1rem; padding-top:.75rem;
        color:#ead9c8; font-size:.72rem; line-height:1.5;}
      .fg-page-head {display:flex; align-items:flex-end; justify-content:space-between; gap:1rem; margin:.1rem 0 .8rem;}
      .fg-head-brand {display:flex; align-items:center; gap:.8rem; min-width:0;}
      .fg-head-mark {display:grid; place-items:center; width:2.7rem; height:2.7rem; border-radius:14px;
        color:#fff8ec; background:linear-gradient(145deg,#c66b25,#9e4312); font-size:1.25rem; flex:0 0 auto;}
      .fg-eyebrow {font-size:.66rem; font-weight:850; letter-spacing:.14em; text-transform:uppercase;
        color:#874719; margin-bottom:.22rem;}
      .fg-page-head h1 {font-family:Georgia,serif; color:#321f0e; font-size:clamp(1.6rem,2.1vw,2.15rem);
        line-height:1.05; letter-spacing:-.025em; margin:0;}
      .fg-page-head p {font-size:.84rem; color:#675747; margin:.28rem 0 0;}
      .fg-head-note {max-width:15rem; color:#5c492f; text-align:right; font-size:.72rem; line-height:1.4;
        padding:.55rem .7rem; border:1px solid #dfd0ae; border-radius:12px; background:#f7edcf;}
      .fg-disclaimer {font-size:.67rem; font-weight:800; letter-spacing:.025em; color:#70401f; margin:.1rem 0 .55rem;}
      [data-testid="stVerticalBlockBorderWrapper"] {border-color:var(--fg-line)!important;
        border-radius:var(--fg-radius)!important; background:rgba(255,253,247,.96);
        box-shadow:0 5px 18px rgba(50,31,14,.045);}
      [data-testid="stMetric"] {background:var(--fg-card); border:1px solid var(--fg-line);
        border-radius:13px; padding:12px 14px; min-height:96px;
        transition:transform .16s ease, box-shadow .16s ease, border-color .16s ease;}
      [data-testid="stMetric"]:hover {transform:translateY(-1px); border-color:#d4c3a3;
        box-shadow:0 3px 10px rgba(50,31,14,.08);}
      [data-testid="stMetricValue"] {font-size:clamp(1.05rem,1.3vw,1.55rem)!important;}
      [data-testid="stAlert"] {border-radius:12px;}
      [data-testid="stDataFrame"] {border:1px solid var(--fg-line); border-radius:12px;}
      .fg-control-panel {padding:.3rem .35rem .08rem;}
      .fg-control-status {display:flex; align-items:center; justify-content:center; min-height:2.7rem;
        border-radius:11px; background:#f4e5bd; color:#644311; padding:.4rem .6rem;
        font-size:.69rem; font-weight:850; letter-spacing:.045em; text-align:center;}
      .fg-section-label {display:flex; align-items:center; gap:.55rem; margin:.1rem 0 .55rem;}
      .fg-section-label:before {content:""; width:4px; height:1.2rem; border-radius:9px; background:#bd570f;}
      .fg-section-label h2 {font-family:Georgia,serif; color:#321f0e; font-size:1.15rem; margin:0;}
      .fg-section-note {color:#6f6358; font-size:.74rem; margin:-.25rem 0 .7rem;}
      .fg-kpi-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
        gap: 0.8rem;
        margin: 0.5rem 0 1rem;
      }
      .fg-kpi-card {
        display: flex;
        align-items: flex-start;
        gap: 0.7rem;
        min-width: 0;
        min-height: 130px;
        border: 1px solid #e1d6c2;
        border-radius: 14px;
        padding: 1rem 1.2rem;
        background: linear-gradient(155deg, #fffef9, #faf6e9);
        box-shadow: 0 3px 8px rgba(50,31,14,0.06);
      }
      .fg-kpi-icon {
        width: 2.4rem;
        height: 2.4rem;
        display: grid;
        place-items: center;
        flex: 0 0 auto;
        border-radius: 12px;
        color: #864515;
        background: #f4e7cb;
      }
      .fg-kpi-icon svg {
        width: 1.4rem;
        height: 1.4rem;
      }
      .fg-kpi-copy {min-width:0;}
      .fg-kpi-title {
        color:#675747;
        font-size:.78rem;
        font-weight:750;
        line-height:1.3;
      }
      .fg-kpi-value {
        color:#321f0e;
        font-size:clamp(1.2rem,1.6vw,1.8rem);
        font-weight:800;
        line-height:1.15;
        letter-spacing:-.025em;
        margin:.2rem 0 .15rem;
      }
      .fg-kpi-detail {
        color:#6f6358;
        font-size:.68rem;
        line-height:1.35;
      }
      .fg-kpi-card.status-low .fg-kpi-value {color:#536c38;}
      .fg-kpi-card.status-moderate .fg-kpi-value {color:#805e10;}
      .fg-kpi-card.status-high .fg-kpi-value {color:#9f3c20;}
      .fg-kpi-card.status-unavailable .fg-kpi-value {color:#62594e; font-size:1.1rem;}
      .fg-reliability {border:1px solid #e1d6c2; border-radius:13px; padding:.8rem .85rem;
        background:#f7f2e4; margin:.25rem 0 .65rem;}
      .fg-reliability-title {font-family:Georgia,serif; font-size:.97rem; font-weight:750; color:#321f0e; margin-bottom:.55rem;}
      .fg-detail-row {display:flex; justify-content:space-between; align-items:flex-start; gap:.7rem;
        border-bottom:1px solid #e8dfcd; padding:.38rem .05rem; font-size:.76rem; line-height:1.35;}
      .fg-detail-row:last-child {border-bottom:0;}
      .fg-detail-value {font-weight:750; text-align:right; color:#493525; overflow-wrap:anywhere;}
      .fg-historical {border-left:4px solid #bd570f; border-radius:0 11px 11px 0;
        background:#f4e7cf; padding:.7rem .8rem; color:#493525; font-size:.77rem; line-height:1.45;}
      .fg-map-legend {display:flex; gap:.46rem .9rem; flex-wrap:wrap; padding:.18rem .1rem .5rem;}
      .fg-map-legend span {white-space:nowrap; font-size:.7rem; font-weight:650;}
      .st-key-fg-dashboard-map [data-testid="stPlotlyChart"], .st-key-fg-risk-map-view [data-testid="stPlotlyChart"] {border-radius:10px; overflow:hidden;}
      .fg-map-caption {display:flex; justify-content:space-between; align-items:center; gap:.5rem;
        color:#6f6358; font-size:.69rem; line-height:1.35; padding:.2rem .1rem 0;}
      .fg-trend-caption {color:#6f6358; font-size:.7rem; line-height:1.4;}
      .fg-status-grid {display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.58rem; align-items:stretch;}
      .fg-status-card {display:flex; flex-direction:column; justify-content:space-between; gap:.45rem;
        min-width:0; min-height:88px; border:1px solid #e4dbc9; border-radius:12px; padding:.72rem .76rem;
        background:linear-gradient(150deg,#fffdf7,#faf6e9); box-shadow:0 2px 6px rgba(50,31,14,.035);}
      .fg-status-name {font-size:.72rem; font-weight:750; color:#493525; line-height:1.35; overflow-wrap:anywhere;}
      .fg-status-count {font-size:1.28rem; font-weight:850; line-height:1.1; color:#321f0e; margin-top:auto;}
      .fg-status-count small {font-size:.66rem; font-weight:600; color:#6f6358;}
      .fg-status-card.status-low {border-top:3px solid #657f45;}
      .fg-status-card.status-low .fg-status-count {color:#536c38;}
      .fg-status-card.status-moderate {border-top:3px solid #dfb13d;}
      .fg-status-card.status-moderate .fg-status-count {color:#805e10;}
      .fg-status-card.status-high {border-top:3px solid #d57522;}
      .fg-status-card.status-high .fg-status-count {color:#a24e18;}
      .fg-status-card.status-very-high {border-top:3px solid #9f3c20;}
      .fg-status-card.status-very-high .fg-status-count {color:#9f3c20;}
      .fg-status-card.status-withheld {border-top:3px solid #ad8a44;}
      .fg-status-card.status-withheld .fg-status-count {color:#74591f;}
      .fg-status-card.status-unavailable {border-top:3px solid #8a8176;}
      .fg-status-card.status-unavailable .fg-status-count {color:#62594e;}
      .fg-risk-distribution-heading {margin:0 0 .24rem; color:#321f0e; font:700 1.12rem/1.25 Georgia,serif;}
      .fg-rank-row {display:grid; grid-template-columns:minmax(95px,1fr) minmax(65px,1.5fr) 66px;
        gap:.48rem; align-items:center; padding:.4rem 0; border-bottom:1px solid #e8dfcd;}
      .fg-rank-row:last-child {border-bottom:0;}
      .fg-rank-name {min-width:0; font-size:.76rem; overflow-wrap:anywhere;}
      .fg-rank-name b {display:block;}
      .fg-rank-name span {display:block; font-size:.65rem; color:#6f6358;}
      .fg-rank-track {height:9px; width:100%; border-radius:999px; background:#eee8d8; overflow:hidden;}
      .fg-rank-score {font-size:.72rem; font-weight:800; text-align:right; overflow-wrap:anywhere;}
      .fg-screen-row {display:grid; grid-template-columns:10px minmax(0,1fr) auto; gap:.48rem;
        align-items:center; padding:.46rem .05rem; border-bottom:1px solid #e8dfcd;}
      .fg-screen-row:last-child {border-bottom:0;}
      .fg-screen-meta {font-size:.68rem; color:#6f6358; margin-top:.12rem;}
      .fg-pill {white-space:normal; border-radius:999px; padding:.2rem .5rem; font-size:.63rem;
        font-weight:800; background:#f3e7c9; color:#533c27; text-align:center;}
      .fg-callout {border-left:4px solid #bd570f; background:#f4e7cf; border-radius:0 11px 11px 0;
        padding:.72rem .85rem; color:#493525; line-height:1.45; font-size:.8rem; margin-bottom:.8rem;}
      .fg-page-intro {max-width:75rem; color:#574431; font-size:.94rem; line-height:1.6; margin:.15rem 0 1rem;}
      .fg-eyebrow-small {font-size:.67rem; font-weight:850; letter-spacing:.13em; text-transform:uppercase;
        color:#874719; margin-bottom:.25rem;}
      .fg-source-card {border:1px solid #dfd4bd; border-radius:13px; padding:.9rem 1rem; margin:.55rem 0;
        background:linear-gradient(145deg,#fffef9,#faf6e9); box-shadow:0 2px 7px rgba(50,31,14,.04);}
      .fg-source-label {color:#874719; font-size:.68rem; font-weight:850; letter-spacing:.08em; text-transform:uppercase;}
      .fg-source-value {font-size:.95rem; font-weight:750; color:#34271f; line-height:1.45; margin-top:.28rem; overflow-wrap:anywhere;}
      .fg-scope-grid {display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.65rem; margin:.45rem 0 1rem;}
      .fg-scope-chip {background:linear-gradient(145deg,#fffdf7,#f5ecd7); border:1px solid #dfd1b6;
        border-top:3px solid #dfb13d; border-radius:11px; padding:.75rem .6rem;
        text-align:center; font-size:.81rem; font-weight:800; color:#493525;}
      .fg-roadmap {counter-reset:roadmap; list-style:none; margin:0; padding:0;}
      .fg-roadmap li {counter-increment:roadmap; display:grid; grid-template-columns:2rem minmax(0,1fr); gap:.55rem;
        align-items:start; padding:.72rem .35rem; border-bottom:1px solid #e8dfcd; line-height:1.5;
        color:#493525;}
      .fg-roadmap li:last-child {border-bottom:0;}
      .fg-roadmap li:before {content:counter(roadmap,decimal-leading-zero); color:#a24e18; font-weight:850; font-size:.75rem;
        border:1px solid #e4d5b8; border-radius:8px; background:#f7edcf; padding:.2rem .25rem; text-align:center;}
      .st-key-fg-page-data-sources [data-testid="stMarkdownContainer"] h3,
      .st-key-fg-page-about [data-testid="stMarkdownContainer"] h3 {font-family:Georgia,serif; color:#321f0e;
        line-height:1.2; margin:.25rem 0 .65rem; padding-bottom:.35rem; border-bottom:1px solid #e8dfcd;}
      .st-key-fg-page-data-sources [data-testid="stMarkdownContainer"] h4,
      .st-key-fg-page-about [data-testid="stMarkdownContainer"] h4 {color:#70401f; margin:.8rem 0 .35rem;}
      .st-key-fg-page-data-sources .fg-detail-row {padding:.48rem .08rem; line-height:1.45;}
      .st-key-fg-page-data-sources .fg-detail-value {max-width:58%;}
      .st-key-fg-page-dashboard, .st-key-fg-page-risk-map,
      .st-key-fg-page-data-sources, .st-key-fg-page-about {animation:fg-page-enter .18s ease-out both;}
      @keyframes fg-page-enter {from {opacity:0; transform:translateY(4px);} to {opacity:1; transform:translateY(0);}}
      [data-testid="stButton"] button, [data-testid="stDownloadButton"] button {
        transition:background-color .15s ease, border-color .15s ease, box-shadow .15s ease, transform .15s ease;}
      [data-testid="stButton"] button:hover, [data-testid="stDownloadButton"] button:hover {transform:translateY(-1px);}
      [data-testid="stSelectbox"] [role="combobox"], [data-testid="stDateInput"] input {
        transition:border-color .15s ease, box-shadow .15s ease;}
      [data-testid="stSelectbox"] [role="combobox"]:hover, [data-testid="stDateInput"] input:hover {border-color:#bd570f;}
      @media (prefers-reduced-motion: reduce) {
        .st-key-fg-page-dashboard, .st-key-fg-page-risk-map, .st-key-fg-page-data-sources, .st-key-fg-page-about {animation:none!important;}
        [data-testid="stSpinner"], [data-testid="stSpinner"] * {animation:none!important; transition:none!important;}
        [data-testid="stMetric"], [data-testid="stMetric"]:hover, [data-testid="stButton"] button,
        [data-testid="stButton"] button:hover, [data-testid="stDownloadButton"] button,
        [data-testid="stDownloadButton"] button:hover, [data-testid="stSelectbox"] [role="combobox"],
        [data-testid="stDateInput"] input, [data-testid="stSidebar"] div[role="radiogroup"] label {
          animation:none!important; transition:none!important; transform:none!important; scroll-behavior:auto!important;}
      }
      @media (max-width: 1100px) {
        .block-container {padding-left:.9rem; padding-right:.9rem;}
        [data-testid="stSidebar"] {min-width:14rem; max-width:14rem;}
        .stApp [data-testid="stHorizontalBlock"] {flex-wrap:wrap!important; align-items:stretch;}
        .stApp [data-testid="stHorizontalBlock"] > [data-testid="column"],
        .stApp [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
          box-sizing:border-box; flex:1 1 300px!important; width:auto!important; min-width:min(100%,300px)!important; max-width:100%;}
        .fg-scope-grid {grid-template-columns:repeat(2,minmax(0,1fr));}
      }
      @media (max-width: 850px) {
        .st-key-mobile_page {display:block!important; margin:3rem 0 .65rem; position:relative; z-index:1000001;}
        .st-key-mobile_page div[role="radiogroup"] {display:flex; flex-wrap:wrap; gap:.25rem;}
        .st-key-mobile_page div[role="radiogroup"] label {
          border:1px solid #dfd4bd; border-radius:9px; padding:.35rem .52rem;
          background:#fffdf7; margin:0;}
        .st-key-mobile_page div[role="radiogroup"] label:has(input:checked) {
          background:#ad4f12; color:#fff8ec;}
        .stApp [data-testid="stHorizontalBlock"] {flex-direction:column!important; flex-wrap:nowrap!important;}
        .stApp [data-testid="stHorizontalBlock"] > [data-testid="column"],
        .stApp [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
          flex:1 1 100%!important; width:100%!important; min-width:0!important; max-width:100%;}
        [data-testid="stSidebar"] {min-width:unset; max-width:unset;}
        [data-testid="stSidebar"][data-collapsed="true"] {
          width:0!important; min-width:0!important; max-width:0!important; flex-basis:0!important;}
        .fg-kpi-grid {grid-template-columns:repeat(2,minmax(0,1fr));}
      }
      @media (max-width: 700px) {
        .block-container {padding:.65rem .65rem 1.2rem;}
        .fg-page-head {align-items:flex-start; flex-direction:column; gap:.45rem;}
        .fg-head-note {max-width:none; text-align:left;}
        .fg-page-head h1 {font-size:1.62rem;}
        .fg-kpi-grid {grid-template-columns:1fr;}
        .fg-status-grid {grid-template-columns:repeat(2,minmax(0,1fr));}
        .fg-detail-row {align-items:flex-start; flex-wrap:wrap;}
        .fg-detail-value {max-width:65%; overflow-wrap:anywhere;}
        .fg-rank-row {grid-template-columns:minmax(0,1fr) 58px;}
        .fg-rank-track {grid-column:1; grid-row:2;}
        .fg-rank-score {grid-column:2; grid-row:1 / span 2;}
        .fg-screen-row {grid-template-columns:10px minmax(0,1fr);}
        .fg-pill {grid-column:2; justify-self:start;}
        .fg-map-caption {align-items:flex-start; flex-direction:column;}
        .fg-map-legend span {white-space:normal;}
      }
    </style>
    """,
    unsafe_allow_html=True,
)

try:
    if st.session_state.get("_fg_initial_load_complete", False):
        BOUNDARY_GEOJSON = boundary_geojson()
        META = dashboard_data.validate_bundle(BOUNDARY_GEOJSON)
        ALL_DATES = date_list()
    else:
        with st.spinner("FloodGuard AI · loading saved historical data…"):
            BOUNDARY_GEOJSON = boundary_geojson()
            META = dashboard_data.validate_bundle(BOUNDARY_GEOJSON)
            ALL_DATES = date_list()
    if not ALL_DATES:
        raise ValueError("The historical archive contains no available dates")
    MIN_DATE = date.fromisoformat(ALL_DATES[0])
    MAX_DATE = date.fromisoformat(ALL_DATES[-1])
    st.session_state["_fg_initial_load_complete"] = True
except DATA_ERRORS:
    logger.exception("Stage 10 startup data validation failed")
    st.error("Historical dashboard resources are missing, unreadable, or invalid. The issue was logged for the project maintainer.", title="Data unavailable")
    st.stop()

for navigation_key in ("active_page", "mobile_page"):
    if navigation_key in st.session_state and st.session_state[navigation_key] not in PAGES:
        st.session_state[navigation_key] = "Dashboard"

with st.sidebar:
    st.markdown(
        '<div class="fg-brand"><span class="fg-drop"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5C9.6 6.4 5 11.2 5 15.3a7 7 0 0 0 14 0C19 11.2 14.4 6.4 12 2.5Z" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M8.4 15.7a3.7 3.7 0 0 0 3.7 3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></span><span>FloodGuard<br>AI</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="fg-nav-note">Historical rainfall screening<br>for safer communities.</div>', unsafe_allow_html=True)
    st.divider()
    page = st.radio(
        "Navigation",
        PAGES,
        key="active_page",
        on_change=lambda: st.session_state.__setitem__("mobile_page", st.session_state["active_page"]),
        label_visibility="collapsed",
        format_func=lambda value: {
            "Dashboard": ":material/dashboard:  Dashboard",
            "Risk Map": ":material/map:  Risk Map",
            "Data & Sources": ":material/database:  Data & Sources",
            "About": ":material/info:  About",
        }[value],
    )
    st.caption("HISTORICAL REPLAY — NOT LIVE DATA")
    st.caption("No verified live rainfall or river-level connection.")

st.radio(
    "Page navigation",
    PAGES,
    key="mobile_page",
    on_change=lambda: st.session_state.__setitem__("active_page", st.session_state["mobile_page"]),
    horizontal=True,
    label_visibility="collapsed",
)

page_copy = {
    "Dashboard": ("Flood-risk screening", "Historical rainfall screening by district", "FOUR-STATE RESEARCH VIEW"),
    "Risk Map": ("Risk map", "Explore saved district screening status", "FOUR-STATE SCOPE"),
    "Data & Sources": ("Data & sources", "Coverage, provenance, and known data limitations", "SOURCE NOTES"),
    "About": ("About FloodGuard AI", "An experimental research prototype for historical screening", "RESEARCH PROTOTYPE"),
}
page_title, page_subtitle, page_tag = page_copy[page]
st.markdown(
    f'<div class="fg-page-head"><div class="fg-head-brand"><span class="fg-head-mark"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5C9.6 6.4 5 11.2 5 15.3a7 7 0 0 0 14 0C19 11.2 14.4 6.4 12 2.5Z" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M8.4 15.7a3.7 3.7 0 0 0 3.7 3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></span>'
    f'<div><div class="fg-eyebrow">FloodGuard AI · Historical monitoring</div><h1>{escape(page_title)}</h1><p>{escape(page_subtitle)}</p></div></div>'
    f'<div class="fg-head-note">{escape(page_tag)}<br>Live rainfall and river feeds are not connected.</div></div>',
    unsafe_allow_html=True,
)
st.markdown(f'<div class="fg-disclaimer">{escape(DISCLAIMER)}</div>', unsafe_allow_html=True)

with st.container(border=True):
    state_col, date_col, district_col, status_col = st.columns([1.0, 1.1, 1.25, .62], vertical_alignment="bottom")
    with state_col:
        if "state" in st.session_state and st.session_state["state"] not in ALLOWED_STATES:
            st.session_state["state"] = ALLOWED_STATES[0]
        selected_state = st.selectbox("State", ALLOWED_STATES, key="state")
    with date_col:
        saved_date = st.session_state.get("analysis_date")
        if saved_date is not None and (
            type(saved_date) is not date or not MIN_DATE <= saved_date <= MAX_DATE
        ):
            st.session_state["analysis_date"] = MAX_DATE
        target_date = st.date_input(
            "Historical target date", value=MAX_DATE, min_value=MIN_DATE,
            max_value=MAX_DATE, format="YYYY-MM-DD", key="analysis_date",
        )
    target = target_date.isoformat()
    score_data_error = None
    try:
        daily = map_snapshot(target[:4])
        day_snapshot = daily.loc[daily["Target_Date"].eq(target)].copy()
    except DATA_ERRORS:
        logger.exception("Annual score data could not be loaded for %s", target[:4])
        score_data_error = True
        day_snapshot = pd.DataFrame(columns=sorted(dashboard_data.ANNUAL_REQUIRED_COLUMNS))
    state_rows = day_snapshot.loc[day_snapshot["State"].eq(selected_state)].copy() if not day_snapshot.empty else pd.DataFrame()
    try:
        boundary_geo = geojson_for_state(BOUNDARY_GEOJSON, selected_state)
    except DATA_ERRORS:
        logger.exception("Regional boundary data could not be loaded")
        st.error("The regional map boundaries are unavailable or invalid. The issue was logged for the project maintainer.", title="Map data unavailable")
        st.stop()
    districts = sorted(
        feature.get("properties", {}).get("district", "")
        for feature in boundary_geo.get("features", [])
        if feature.get("properties", {}).get("district")
    )
    if "district" in st.session_state:
        current_district = st.session_state["district"]
        if current_district is not None and current_district not in districts:
            st.session_state["district"] = districts[0] if districts else None
    with district_col:
        district_options = [None, *districts]
        district_widget_args = {"key": "district"}
        if "district" not in st.session_state:
            district_widget_args["index"] = 1 if districts else 0
        district = st.selectbox(
            "District / monitoring area",
            district_options,
            format_func=lambda value: value if value is not None else "Select a district",
            **district_widget_args,
        )
    with status_col:
        st.markdown('<div class="fg-control-status">● HISTORICAL<br>DATA</div>', unsafe_allow_html=True)

def fmt_number(value, suffix="", digits=2):
    if value is None or pd.isna(value) or str(value).strip() == "":
        return "Unavailable"
    try:
        return f"{float(value):,.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "Unavailable"


def exact_history(boundary_id):
    if not boundary_id:
        return pd.DataFrame()
    try:
        return district_history(str(boundary_id))
    except DATA_ERRORS:
        logger.exception("Saved district rainfall history could not be loaded for boundary %s", boundary_id)
        st.warning("Saved rainfall history is unavailable or invalid for this district. The issue was logged.")
        return pd.DataFrame()


def map_figure(snapshot, state, height=610, focus_district=None):
    rows = map_rows_for_state(snapshot, state)
    geo = geojson_for_state(boundary_geo, state)
    if not geo.get("features"):
        raise ValueError(f"Validated map boundaries are unavailable for {state}")
    if rows.empty:
        return None
    rows["Map_Status"] = rows.apply(map_status, axis=1)
    rows["GeoJSON_id_number"] = pd.to_numeric(rows["GeoJSON_id"], errors="raise").astype(int)
    center, zoom = map_view_for_selection(state, focus_district)
    fig = px.choropleth_map(
        rows,
        geojson=geo,
        locations="GeoJSON_id_number",
        featureidkey="properties.id",
        color="Map_Status",
        color_discrete_map=MAP_STATUS_COLORS,
        category_orders={"Map_Status": list(MAP_STATUS_COLORS)},
        custom_data=["State", "District", "Risk_Category", "Risk_Score_Available", "Coverage_Gate_Status", "Data_Quality_Status"],
        hover_name="District",
        map_style="white-bg",
        center=center,
        zoom=zoom,
        opacity=0.9,
    )
    fig.update_traces(
        marker_line_color="#fffaf2",
        marker_line_width=0.7,
        hovertemplate=(
            "<b>%{customdata[1]}</b><br>State: %{customdata[0]}<br>"
            "Screening status: %{customdata[2]}<br>Score available: %{customdata[3]}<br>"
            "Coverage: %{customdata[4]}<br>Data quality: %{customdata[5]}<extra></extra>"
        ),
    )
    fig.update_layout(
        height=height,
        margin={"l": 0, "r": 0, "t": 6, "b": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#34271f",
        showlegend=False,
    )
    return fig


def render_map(snapshot, state, height=610, focus_district=None):
    try:
        fig = map_figure(snapshot, state, height=height, focus_district=focus_district)
    except DATA_ERRORS:
        logger.exception("Map construction failed for %s on %s", state, target)
        st.warning("The map is unavailable for these saved records. The issue was logged for the project maintainer.")
        return
    if fig is None:
        st.warning(f"No saved map rows are available for {state} on {target}.")
        return
    try:
        st.plotly_chart(
            fig,
            key=f"risk_map_{state}_{target}_{height}_{focus_district or 'state'}",
            width="stretch",
            alt=f"Historical experimental rainfall screening for districts in {state} on {target}",
        )
    except DATA_ERRORS:
        logger.exception("Map rendering failed for %s on %s", state, target)
        st.warning("The map could not be displayed. The issue was logged for the project maintainer.")


def render_legend():
    items = [
        ("LOW", MAP_STATUS_COLORS["LOW"]),
        ("MODERATE", MAP_STATUS_COLORS["MODERATE"]),
        ("HIGH", MAP_STATUS_COLORS["HIGH"]),
        ("VERY HIGH", MAP_STATUS_COLORS["VERY HIGH"]),
        ("Category withheld: low coverage", MAP_STATUS_COLORS["Category withheld: low coverage"]),
        ("Score unavailable", MAP_STATUS_COLORS["Score unavailable"]),
    ]
    labels = "".join(
        f'<span><b style="color:{color}" aria-hidden="true">●</b> {escape(label)}</span>'
        for label, color in items
    )
    st.markdown(f'<div class="fg-map-legend" role="list" aria-label="Map screening status legend">{labels}</div>', unsafe_allow_html=True)

def district_records(snapshot, state):
    rows = map_rows_for_state(snapshot, state)
    if rows.empty:
        return rows
    rows["Screening status"] = rows.apply(map_status, axis=1)
    rows["Experimental score"] = rows.apply(
        lambda row: fmt_number(row["Risk_Score"], digits=1)
        if row["Risk_Score_Available"] == "1" else "Unavailable",
        axis=1,
    )
    rows["Coverage"] = rows["Coverage_Gate_Status"].map(
        {"PASS_AT_LEAST_80_PERCENT": "At least 80%", "FAIL_BELOW_80_PERCENT": "Limited coverage"}
    ).fillna("Unavailable")
    rows["Score_Sort"] = pd.to_numeric(rows["Risk_Score"], errors="coerce")
    rows = rows.sort_values(["Risk_Score_Available", "Score_Sort"], ascending=[False, False], na_position="last")
    return rows[["District", "Screening status", "Experimental score", "Coverage", "Data_Quality_Status", "Score_Unavailable_Reason"]].rename(
        columns={"Data_Quality_Status": "Data quality", "Score_Unavailable_Reason": "Unavailable reason"}
    )


def recent_screening(state, target_value, days=7):
    dates = pd.date_range(max(MIN_DATE, target_value - timedelta(days=days - 1)), target_value, freq="D")
    try:
        rows = recent_snapshot_rows(state, dates.strftime("%Y-%m-%d"), current_snapshot=daily)
    except DATA_ERRORS:
        logger.exception("Recent screening records could not be loaded for %s", state)
        st.warning("Recent screening records are unavailable or invalid. The issue was logged.")
        return pd.DataFrame(columns=["Target date", "District", "Screening status", "Experimental score", "Coverage"])
    if rows.empty:
        return pd.DataFrame(columns=["Target date", "District", "Screening status", "Experimental score", "Coverage"])
    rows["Screening status"] = rows.apply(map_status, axis=1)
    rows["Experimental score"] = rows.apply(
        lambda row: fmt_number(row["Risk_Score"], digits=1)
        if row["Risk_Score_Available"] == "1" else "Unavailable", axis=1
    )
    result = rows[["Target_Date", "District", "Screening status", "Experimental score", "Coverage_Gate_Status"]]
    result = result.sort_values(["Target_Date", "District"], ascending=[False, True])
    return result.rename(columns={"Target_Date": "Target date", "Coverage_Gate_Status": "Coverage"})


selected_record = pd.DataFrame()
selected_history = pd.DataFrame()
if district and not state_rows.empty:
    found = state_rows.loc[state_rows["District"].eq(district)]
    if not found.empty:
        selected_record = found.iloc[[0]].copy()
        boundary_id = selected_record.iloc[0]["Rainfall_Boundary_Record_Index"]
        selected_history = exact_history(boundary_id)
        if not selected_history.empty:
            selected_history = selected_history.loc[selected_history["date"].le(target)].copy()


def _render_trend_panel():
    st.subheader("Rainfall trend")
    if not district:
        st.info("Select a district to view its saved rainfall history.")
        return
    if selected_history.empty:
        st.info("No district rainfall history is available for this selection.")
        return
    default_start = max(MIN_DATE, target_date - timedelta(days=29))
    trend_key = f"trend_range_{selected_state}_{target}"
    saved_range = st.session_state.get(trend_key)
    if saved_range is not None:
        if isinstance(saved_range, tuple) and len(saved_range) == 2:
            range_valid = all(type(value) is date and MIN_DATE <= value <= target_date for value in saved_range)
            range_valid = range_valid and saved_range[0] <= saved_range[1]
        else:
            range_valid = type(saved_range) is date and MIN_DATE <= saved_range <= target_date
        if not range_valid:
            del st.session_state[trend_key]
    selected_range = st.date_input(
        "Date range",
        value=(default_start, target_date),
        min_value=MIN_DATE,
        max_value=target_date,
        format="YYYY-MM-DD",
        key=trend_key,
    )
    if isinstance(selected_range, tuple) and len(selected_range) == 2:
        start_date = selected_range[0]
        end_date = selected_range[-1]
    elif type(selected_range) is date:
        start_date = end_date = selected_range
    else:
        st.info("Choose a valid date range within the available archive.")
        return
    if start_date > end_date:
        st.info("The selected date range is invalid. Choose a start date on or before the end date.")
        return
    series = selected_history.loc[
        selected_history["date"].between(start_date.isoformat(), end_date.isoformat())
    ].copy()
    if series.empty:
        st.info("No saved feature rows match this date range.")
        return
    series["Rainfall_Prev_1d_mm"] = pd.to_numeric(series["Rainfall_Prev_1d_mm"], errors="coerce")
    if not series["Rainfall_Prev_1d_mm"].notna().any():
        st.info("No valid rainfall observations are available in this date range. Missing values remain unavailable.")
        return
    fig = px.bar(
        series,
        x="date",
        y="Rainfall_Prev_1d_mm",
        labels={"date": "Target date", "Rainfall_Prev_1d_mm": "Rainfall (mm)"},
        title=f"Rainfall trend · {district}",
        template="plotly_white",
    )
    fig.update_traces(
        marker_color="#b85a18",
        marker_line_width=0,
        hovertemplate="Target date: %{x|%d %b %Y}<br>Previous-day rainfall: %{y:.1f} mm<extra></extra>",
    )
    fig.update_layout(
        height=260,
        margin={"l": 8, "r": 8, "t": 46, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Arial, sans-serif", size=12, color="#34271f"),
        title=dict(font=dict(family="Georgia, serif", size=16, color="#321f0e"), x=0, xanchor="left"),
        hoverlabel=dict(bgcolor="#fffdf7", bordercolor="#dfd4bd", font=dict(color="#34271f", size=12)),
        showlegend=False,
        bargap=.24,
    )
    fig.update_xaxes(
        showgrid=False, tickformat="%d %b", tickangle=0, title_text="Target date",
        title_font=dict(size=11, color="#574431"), tickfont=dict(size=10, color="#574431"),
        showline=True, linecolor="#dfd4bd", automargin=True,
    )
    fig.update_yaxes(
        showgrid=True, gridcolor="#e8dfcd", gridwidth=1, rangemode="tozero", title_text="Rainfall (mm)",
        title_font=dict(size=11, color="#574431"), tickfont=dict(size=10, color="#574431"),
        zeroline=False, showline=False, automargin=True,
    )
    st.plotly_chart(fig, width="stretch", alt=f"Historical previous-day rainfall bars for {district}; gaps are not imputed")
    st.caption("Dates are target dates; each bar shows the stored previous-day rainfall feature. Missing observations remain missing and valid zeros remain 0.0 mm.")

def trend_panel():
    try:
        _render_trend_panel()
    except DATA_ERRORS:
        logger.exception("Rainfall trend panel failed for %s", district)
        st.warning("The rainfall trend is unavailable for these saved records. The issue was logged for the project maintainer.")

def selected_summary_card():
    st.subheader("Selected district screening")
    if selected_record.empty:
        st.info("Choose a district from the sidebar to inspect its saved score and data quality.")
        st.caption(f"Selected state: {selected_state}")
        return
    rec = selected_record.iloc[0]
    status = map_status(rec)
    st.markdown(f"### {district}")
    st.caption(f"{selected_state} · target date {target}")
    st.metric("Selected area", district, border=True)
    st.metric("Experimental category", status, border=True)
    score = fmt_number(rec["Risk_Score"], digits=1) if rec["Risk_Score_Available"] == "1" else "Unavailable"
    st.metric("Experimental risk score", score, border=True)
    obs = selected_history.loc[selected_history["date"].eq(target)] if not selected_history.empty else pd.DataFrame()
    if obs.empty:
        st.metric("Previous-day rainfall", "Unavailable", border=True)
        st.metric("Rainfall completeness", "Unavailable", border=True)
    else:
        feature = obs.iloc[0]
        st.metric("Previous-day rainfall", fmt_number(feature.get("Rainfall_Prev_1d_mm"), " mm"), border=True)
        st.metric("Previous 7-day completeness", fmt_number(feature.get("Rainfall_Completeness_Prev_7d_Pct"), "%", 1), border=True)
        if rec["Risk_Score_Available"] != "1":
            st.warning(rec["Score_Unavailable_Reason"] or "Score unavailable; no category is assigned.", title="Score unavailable")
        elif rec["Coverage_Gate_Status"] != "PASS_AT_LEAST_80_PERCENT":
            st.warning("Coverage is below the approved 80% gate. The risk category is withheld.", title="Limited spatial coverage")


def data_reliability_card():
    st.subheader("Data reliability")
    if selected_record.empty:
        st.info("District-level quality fields appear after selecting a district.")
        return
    rec = selected_record.iloc[0]
    obs = selected_history.loc[selected_history["date"].eq(target)] if not selected_history.empty else pd.DataFrame()
    if obs.empty:
        st.write("Rainfall data: **Unavailable for this target date**")
        st.write("Spatial coverage: **Unavailable**")
        st.write("Last available observation: **Unavailable**")
    else:
        feature = obs.iloc[0]
        st.write(f"Rainfall data: **{'Available' if feature.get('Rainfall_Prev_1d_mm','') != '' else 'Unavailable'}**")
        st.write(f"Spatial coverage, minimum previous day: **{fmt_number(feature.get('Spatial_Coverage_Min_Prev_1d'), '%', 1)}**")
        st.write(f"Spatial coverage, mean previous 7 days: **{fmt_number(feature.get('Spatial_Coverage_Mean_Prev_7d'), '%', 1)}**")
        st.write(f"7-day valid observations: **{feature.get('Valid_Rainfall_Days_Prev_7d','Unavailable')} / {feature.get('Expected_Rainfall_Days_Prev_7d','Unavailable')}**")
        last_observation = feature.get("Previous_Rainfall_Date_Used", "")
        st.write(f"Latest rainfall observation used: **{last_observation or 'Unavailable'}**")
    coverage_text = "Available (at least 80%)" if rec["Coverage_Gate_Status"] == "PASS_AT_LEAST_80_PERCENT" else "Limited or unavailable"
    st.write(f"Coverage gate: **{coverage_text}**")
    st.write("Live feed: **Not connected**")
    st.write("Boundary vintage: **Current validated boundary; historical identity may differ**")


def rainfall_window_cards():
    st.subheader("Rainfall feature breakdown · dates before target")
    if selected_record.empty or selected_history.empty:
        st.info("Select a district with saved feature history to view the rainfall windows.")
        return
    exact = selected_history.loc[selected_history["date"].eq(target)]
    if exact.empty:
        st.info("No saved feature row is available for this district and target date.")
        return
    feature = exact.iloc[0]
    columns = st.columns(5)
    for days, field in WINDOW_COLUMNS.items():
        columns[list(WINDOW_COLUMNS).index(days)].metric(
            f"Previous {days} days",
            fmt_number(feature.get(field), " mm"),
            border=True,
        )


def detail_row(label, value, color="#493525"):
    st.markdown(
        f'<div class="fg-detail-row"><span>{escape(str(label))}</span>'
        f'<span class="fg-detail-value" style="color:{color}">{escape(str(value))}</span></div>',
        unsafe_allow_html=True,
    )


KPI_ICONS = {
    "rain": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 15.5h10a3.5 3.5 0 0 0 .2-7 5.5 5.5 0 0 0-10.5 1.2A3 3 0 0 0 7 15.5Z"/><path d="m9 18-1 2m5-2-1 2m5-2-1 2"/></svg>',
    "risk": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 20 6v5c0 5-3.3 8.5-8 10-4.7-1.5-8-5-8-10V6l8-3Z"/><path d="M12 8v4m0 3h.01"/></svg>',
    "data": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="5" rx="7.5" ry="2.8"/><path d="M4.5 5v6c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8V5M4.5 11v6c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-6"/></svg>',
}


def render_kpi_grid(cards):
    items = []
    status_classes = {
        "LOW": "status-low",
        "MODERATE": "status-moderate",
        "HIGH": "status-high",
        "VERY HIGH": "status-high",
        "Category withheld: low coverage": "status-moderate",
        "Score unavailable": "status-unavailable",
        "Unavailable": "status-unavailable",
    }
    for title, value, detail, icon in cards:
        status_class = status_classes.get(value, "")
        icon_svg = KPI_ICONS[icon]
        items.append(
            f'<article class="fg-kpi-card {status_class}" role="group" aria-label="{escape(title)}: {escape(value)}">'
            f'<span class="fg-kpi-icon">{icon_svg}</span><div class="fg-kpi-copy">'
            f'<div class="fg-kpi-title">{escape(title)}</div><div class="fg-kpi-value">{escape(value)}</div>'
            f'<div class="fg-kpi-detail">{escape(detail)}</div></div></article>'
        )
    st.markdown('<div class="fg-kpi-grid">' + ''.join(items) + '</div>', unsafe_allow_html=True)


def render_status_distribution(ranked):
    st.markdown('<h3 class="fg-risk-distribution-heading">Experimental risk by district</h3>', unsafe_allow_html=True)
    st.caption("Counts reflect saved target-date screening statuses in the selected state; they are not flood-event totals.")
    if ranked.empty:
        st.info("No saved district scores are available for this state and date.")
        return
    counts = ranked["Screening status"].value_counts()
    cards = []
    status_classes = {
        "LOW": "status-low",
        "MODERATE": "status-moderate",
        "HIGH": "status-high",
        "VERY HIGH": "status-very-high",
        "Category withheld: low coverage": "status-withheld",
        "Score unavailable": "status-unavailable",
    }
    for label in ("LOW", "MODERATE", "HIGH", "VERY HIGH", "Category withheld: low coverage", "Score unavailable"):
        count = int(counts.get(label, 0))
        cards.append(
            f'<div class="fg-status-card {status_classes[label]}"><div class="fg-status-name">{escape(label)}</div>'
            f'<div class="fg-status-count">{count} <small>districts</small></div></div>'
        )
    st.markdown('<div class="fg-status-grid">' + ''.join(cards) + '</div>', unsafe_allow_html=True)
    st.caption("Unavailable scores and withheld categories are counted separately from LOW.")


def render_recent_screening_list(recent):
    st.subheader("Recent historical screening")
    st.caption("Saved records for the selected state; not operational alerts or confirmed events.")
    if recent.empty:
        st.info("No saved screening rows are available in the recent date window.")
        return
    for _, item in recent.head(6).iterrows():
        status = str(item["Screening status"])
        dot = MAP_STATUS_COLORS.get(status, MAP_STATUS_COLORS["Score unavailable"])
        name = escape(str(item["District"]))
        record_date = escape(str(item["Target date"]))
        score = escape(str(item["Experimental score"]))
        label = escape(status)
        st.markdown(
            f'<div class="fg-screen-row"><span style="color:{dot};font-size:.95rem" aria-hidden="true">●</span>'
            f'<div><b>{name}</b><div class="fg-screen-meta">{record_date} · experimental score {score}</div></div>'
            f'<span class="fg-pill">{label}</span></div>',
            unsafe_allow_html=True,
        )
    with st.expander("All recent screening records"):
        st.dataframe(recent, hide_index=True, height=230, width="stretch", alt="Recent historical screening records for the selected state")


def render_dashboard():
    record = selected_record.iloc[0] if not selected_record.empty else None
    observation = (
        selected_history.loc[selected_history["date"].eq(target)].iloc[0]
        if not selected_history.empty and selected_history["date"].eq(target).any()
        else None
    )
    rain_value = fmt_number(
        observation.get("Rainfall_Prev_1d_mm") if observation is not None else None,
        " mm",
        1,
    )
    rainfall_date = "Unavailable"
    if observation is not None:
        raw_date = observation.get("Previous_Rainfall_Date_Used", "")
        if pd.notna(raw_date) and str(raw_date).strip():
            rainfall_date = str(raw_date)
    risk_status = map_status(record) if record is not None else "Select district"
    risk_score = (
        fmt_number(record["Risk_Score"], digits=2)
        if record is not None and record["Risk_Score_Available"] == "1"
        else "Unavailable"
    )
    coverage = "Unavailable"
    if record is not None:
        coverage = "At least 80% (gate passed)" if record["Coverage_Gate_Status"] == "PASS_AT_LEAST_80_PERCENT" else "Below 80% or unavailable"

    map_col, overview_col = st.columns([1.22, .88], gap="medium")
    with map_col.container(border=True):
        st.markdown('<div class="fg-eyebrow-small">Geographic screening</div>', unsafe_allow_html=True)
        st.markdown(f"### {escape(selected_state)} district map")
        st.markdown('<div class="fg-section-note">Saved experimental screening by district for the selected historical date.</div>', unsafe_allow_html=True)
        render_legend()
        with st.container(key="fg-dashboard-map", border=False):
            render_map(day_snapshot, selected_state, height=450, focus_district=district)
        st.markdown(
            '<div class="fg-map-caption"><span>Validated current rainfall boundaries</span>'
            '<span>Historical district extents may differ</span></div>',
            unsafe_allow_html=True,
        )

    with overview_col.container(border=True):
        st.markdown('<div class="fg-eyebrow-small">Monitoring overview</div>', unsafe_allow_html=True)
        st.markdown("### Selected district")
        if district:
            st.markdown(f'<div class="fg-section-note">{escape(district)}, {escape(selected_state)} · target {escape(target)}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="fg-section-note">State view · {escape(selected_state)} · target {escape(target)}</div>', unsafe_allow_html=True)
        rain_detail = f"Observation date: {rainfall_date}" if rain_value != "Unavailable" else "No saved rainfall observation for this selection"
        risk_detail = f"Experimental score: {risk_score} · coverage: {coverage}"
        render_kpi_grid([
            ("Previous-day rainfall", rain_value, rain_detail, "rain"),
            ("Experimental risk status", risk_status, risk_detail, "risk"),
        ])
        with st.container(border=True):
            st.markdown('<div class="fg-reliability-title">Data reliability</div>', unsafe_allow_html=True)
            rain_status = "Available" if rain_value != "Unavailable" else "Unavailable"
            detail_row("Rainfall observation", rain_status, "#476b39" if rain_value != "Unavailable" else "#6f6358")
            detail_row("Spatial coverage gate", coverage, "#476b39" if coverage.startswith("At least") else "#8b481f")
            quality = (
                str(record["Data_Quality_Status"]).replace("_", " ").lower().capitalize()
                if record is not None else "Select a district"
            )
            detail_row("Stored data-quality status", quality)
            detail_row("River-level observations", "Not connected", "#6f6358")
        status_detail = (
            f"{district}, {selected_state}: saved status {risk_status}; score {risk_score}; coverage {coverage}."
            if record is not None
            else f"No district is selected in {selected_state}; district-specific screening values are unavailable."
        )
        st.markdown(
            '<div class="fg-historical"><b>Historical screening only</b><br>'
            f'{escape(status_detail)} Not a live alert, flood confirmation, or forecast.</div>',
            unsafe_allow_html=True,
        )
        with st.expander("Rainfall windows and district detail"):
            selected_summary_card()
            rainfall_window_cards()

    st.markdown('<div class="fg-eyebrow-small">Rainfall and risk context</div>', unsafe_allow_html=True)
    trend_col, distribution_col = st.columns([1.08, .92], gap="medium")
    with trend_col.container(border=True):
        trend_panel()
    ranked = district_records(day_snapshot, selected_state)
    with distribution_col.container(border=True):
        render_status_distribution(ranked)

    overview_col, recent_col = st.columns([1.25, .75], gap="medium")
    with overview_col.container(border=True):
        st.subheader("District screening overview")
        st.caption("Saved district rows and their separate coverage/data-quality states.")
        if ranked.empty:
            st.info("No saved district screening rows are available for this state and date.")
        else:
            st.dataframe(
                ranked,
                hide_index=True,
                height=360,
                width="stretch",
                alt=f"Historical district screening overview for {selected_state}",
            )
    with recent_col.container(border=True):
        render_recent_screening_list(recent_screening(selected_state, target_date))
    st.warning(DISCLAIMER, title="Experimental screening only")
def render_risk_map():
    st.markdown(
        '<div class="fg-callout">Historical replay only. Screening categories are not flood occurrence claims or forecasts.</div>',
        unsafe_allow_html=True,
    )
    map_col, detail_col = st.columns([1.35, .85], gap="medium")
    with map_col.container(border=True):
        st.markdown('<div class="fg-eyebrow-small">Geographic screening</div>', unsafe_allow_html=True)
        st.markdown(f"### {escape(selected_state)} · {target}")
        render_legend()
        if district:
            st.caption(f"Map focused on {district}, {selected_state}; colors retain their saved status meanings.")
        else:
            st.caption(f"State-level map for {selected_state}; select a district to focus the map and details.")
        with st.container(key="fg-risk-map-view", border=False):
            render_map(day_snapshot, selected_state, height=500, focus_district=district)
    ranked = district_records(day_snapshot, selected_state)
    with detail_col.container(border=True):
        st.markdown('<div class="fg-eyebrow-small">Selected monitoring area</div>', unsafe_allow_html=True)
        if ranked.empty:
            st.info("No saved district scores are available for this state/date.")
        elif district:
            selected_rows = ranked.loc[ranked["District"].eq(district)]
            st.markdown(f"### {escape(district)}")
            st.caption(f"{selected_state} · target date {target}")
            if selected_rows.empty:
                st.info(f"No saved district score is available for {district} on {target}.")
            else:
                selected = selected_rows.iloc[0]
                render_kpi_grid([
                    ("Screening status", str(selected["Screening status"]), "Historical experimental category", "risk"),
                    ("Experimental score", str(selected["Experimental score"]), "Not a calibrated probability", "risk"),
                    ("Spatial coverage", str(selected["Coverage"]), "Category gate status", "risk"),
                ])
                if selected["Experimental score"] == "Unavailable":
                    st.warning("Score unavailable; no LOW category is assigned.", title="Unavailable score")
                elif selected["Coverage"] == "Limited coverage":
                    st.warning("Coverage is below the 80% gate; the category is withheld.", title="Limited coverage")
                st.caption("Saved historical experimental screening; not a forecast or confirmed flood event.")
        else:
            st.markdown("### State view")
            st.caption(f"{selected_state} · target date {target}")
            st.info("Select a district to focus the map and review its screening details.")
    with st.container(border=True):
        st.markdown('<div class="fg-eyebrow-small">District screening records</div>', unsafe_allow_html=True)
        if ranked.empty:
            st.info("No saved district scores are available for this state/date.")
        elif district:
            selected_rows = ranked.loc[ranked["District"].eq(district)]
            st.subheader(f"{district} screening detail")
            if selected_rows.empty:
                st.info(f"No saved district score is available for {district} on {target}.")
            else:
                st.dataframe(selected_rows, hide_index=True, width="stretch", alt=f"Risk and coverage status for {district} in {selected_state}")
        else:
            st.subheader("All district screening details")
            st.dataframe(ranked, hide_index=True, width="stretch", alt=f"Risk and coverage status for districts in {selected_state}")
def render_sources():
    st.markdown('<div class="fg-page-intro">Historical archive information, source provenance, and known coverage limitations for the regional prototype.</div>', unsafe_allow_html=True)
    render_kpi_grid([
        ("Archive period", f"{META['min_date']} – {META['max_date']}", "Saved historical feature archive", "data"),
        ("Boundary-date rows", f"{META['score_rows']:,}", "Existing cached score records", "data"),
        ("Rainfall boundaries", str(META["unique_boundary_ids"]), "Validated current boundary features", "data"),
        ("Regional scope", "4 states", "Andhra Pradesh · Karnataka · Kerala · Tamil Nadu", "data"),
    ])
    source_col, access_col = st.columns([1.1, .9], gap="medium")
    with source_col.container(border=True):
        st.markdown('<div class="fg-eyebrow-small">Source provenance</div>', unsafe_allow_html=True)
        st.markdown("### Historical rainfall data")
        st.markdown(
            "The dashboard reads the project’s saved Stage 3 district rainfall features and experimental score outputs prepared from historical IMD gridded rainfall. District rainfall used area-weighted boundary coverage from validated rainfall polygons. Stage 10 reads cached annual scores and per-boundary feature histories; it does not recalculate scores."
        )
        st.markdown('<div class="fg-source-card"><div class="fg-source-label">Rainfall preparation</div><div class="fg-source-value">Area-weighted district extraction with stored spatial coverage</div></div>', unsafe_allow_html=True)
        st.markdown('<div class="fg-source-card"><div class="fg-source-label">Data use</div><div class="fg-source-value">Saved historical records · no connected live feeds</div></div>', unsafe_allow_html=True)
    with access_col.container(border=True):
        st.markdown('<div class="fg-eyebrow-small">Availability and freshness</div>', unsafe_allow_html=True)
        st.markdown("### What is available")
        detail_row("Historical rainfall archive", "Available", "#476b39")
        detail_row("Live rainfall API", "Not connected", "#6f6358")
        detail_row("River-level observations", "Not connected", "#6f6358")
        detail_row("Application retrieval time", "Unavailable", "#6f6358")
        detail_row("Publication latency", "Unverified", "#6f6358")
        st.caption("No current measurements or operational alert status are represented.")
    with st.container(border=True):
        st.markdown('<div class="fg-eyebrow-small">Quality, method, and known limitations</div>', unsafe_allow_html=True)
        st.markdown("### How to interpret the stored data")
        left, right = st.columns(2, gap="medium")
        with left:
            st.markdown(
                "- Daily features use rainfall dates strictly before each target date.\n"
                "- Stored windows cover the preceding 1, 3, 7, 14, and 30 calendar days.\n"
                "- Missing rainfall stays missing; measured zero rainfall remains a valid zero.\n"
                "- The experimental category gate requires at least 80% spatial coverage."
            )
        with right:
            st.markdown(
                "- Incomplete or unavailable scores remain separate from LOW.\n"
                "- The 94 polygons are current rainfall-boundary features and may differ from historical district boundaries.\n"
                "- Inventory silence is not a non-flood label.\n"
                "- Historical evidence reviews remain unadjudicated."
            )
    with st.expander("Source file fingerprints"):
        st.code(f"Stage 3 scores SHA-256: {META['source_score_sha256']}\nStage 3 features SHA-256: {META['source_feature_sha256']}")
    st.warning(DISCLAIMER, title="Interpretation limit")
def render_about():
    st.markdown(
        '<div class="fg-page-intro">FloodGuard AI is an experimental decision-support project exploring how historical rainfall features may support district-level screening and further investigation.</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="fg-eyebrow-small">Regional prototype · four states only</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="fg-scope-grid"><div class="fg-scope-chip">Andhra Pradesh</div>'
        '<div class="fg-scope-chip">Karnataka</div><div class="fg-scope-chip">Kerala</div>'
        '<div class="fg-scope-chip">Tamil Nadu</div></div>',
        unsafe_allow_html=True,
    )
    capability_col, method_col = st.columns([1, 1], gap="medium")
    with capability_col.container(border=True):
        st.markdown('<div class="fg-eyebrow-small">System capability</div>', unsafe_allow_html=True)
        st.markdown("### What the prototype does")
        st.write("It displays existing retrospective rainfall-derived experimental scores, data completeness, and spatial-coverage information for the selected state, district, and target date.")
        st.markdown("#### What it does not do")
        st.markdown(
            "- It does not provide live rainfall, river gauges, or flood alerts.\n"
            "- It does not estimate calibrated flood probabilities.\n"
            "- It does not confirm that a flood occurred or will occur.\n"
            "- A validated supervised ML model has not been trained because a defensible adjudicated validation dataset is not available."
        )
    with method_col.container(border=True):
        st.markdown('<div class="fg-eyebrow-small">Method at a glance</div>', unsafe_allow_html=True)
        st.markdown("### Historical rainfall screening")
        st.markdown(
            "The interface presents previously generated features and experimental categories for a selected district and date. Rainfall values are retained as stored, missing values remain unavailable, and category availability follows the existing spatial-coverage gate. No score is described as a probability."
        )
        st.markdown('<div class="fg-source-card"><div class="fg-source-label">Interpretation</div><div class="fg-source-value">Exploratory screening only · not a calibrated flood probability</div></div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div class="fg-eyebrow-small">Research roadmap</div>', unsafe_allow_html=True)
        st.markdown("### Work needed before operational use")
        st.markdown(
            '<ol class="fg-roadmap"><li>Acquire and independently adjudicate historical flood and monitoring evidence.</li>'
            '<li>Establish a locked independent validation set.</li>'
            '<li>Reassess model feasibility only after defensible labels and coverage are available.</li>'
            '<li>Verify authenticated data feeds and publication latency before considering live use.</li></ol>',
            unsafe_allow_html=True,
        )
    st.warning(DISCLAIMER, title="Experimental research prototype")
page_key = {
    "Dashboard": "fg-page-dashboard",
    "Risk Map": "fg-page-risk-map",
    "Data & Sources": "fg-page-data-sources",
    "About": "fg-page-about",
}[page]
with st.container(key=page_key):
    if score_data_error and page in {"Dashboard", "Risk Map"}:
        st.error(f"Saved annual screening data for {target[:4]} could not be loaded. Dashboard and map results are unavailable; the issue was logged for the project maintainer.", title="Data unavailable")
    elif page == "Dashboard":
        render_dashboard()
    elif page == "Risk Map":
        render_risk_map()
    elif page == "Data & Sources":
        render_sources()
    elif page == "About":
        render_about()

st.divider()
st.caption(DISCLAIMER)
