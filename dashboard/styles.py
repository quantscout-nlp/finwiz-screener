"""Hedge-fund-style dark theme for the Finwiz dashboard."""

HF_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
}

.main .block-container {
    padding-top: 1.5rem;
    max-width: 1400px;
}

.finwiz-title {
    font-size: 1.55rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: #e8edf5;
    margin-bottom: 0.15rem;
}

.finwiz-sub {
    color: #8b9cb3;
    font-size: 0.88rem;
    margin-bottom: 1.25rem;
}

.kpi-row { display: flex; gap: 0.75rem; flex-wrap: wrap; margin-bottom: 1rem; }

.kpi-card {
    background: linear-gradient(145deg, #141b28 0%, #101722 100%);
    border: 1px solid #243044;
    border-radius: 10px;
    padding: 0.85rem 1rem;
    min-width: 140px;
    flex: 1;
}

.kpi-label { color: #7d8fa8; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; }
.kpi-value { color: #f0f4fa; font-size: 1.45rem; font-weight: 700; font-family: 'IBM Plex Mono', monospace; }
.kpi-delta { font-size: 0.78rem; margin-top: 0.15rem; }

.action-buy { color: #3dd68c; font-weight: 700; }
.action-hold { color: #f5c842; font-weight: 700; }
.action-sell { color: #ff9f43; font-weight: 700; }
.action-avoid { color: #ff6b6b; font-weight: 700; }

.ticker-card {
    background: #121a27;
    border: 1px solid #243044;
    border-radius: 12px;
    padding: 1rem 1.1rem;
    margin-bottom: 0.75rem;
}

.ticker-head { font-size: 1.15rem; font-weight: 700; color: #eef2f8; }
.ticker-meta { color: #8b9cb3; font-size: 0.82rem; }

.reason-pill {
    display: inline-block;
    background: #1a2435;
    border: 1px solid #2d3f58;
    border-radius: 999px;
    padding: 0.15rem 0.55rem;
    margin: 0.15rem 0.25rem 0.15rem 0;
    font-size: 0.74rem;
    color: #b8c7da;
}

.sidebar-brand {
    font-weight: 700;
    font-size: 0.95rem;
    color: #dbe4f2;
    padding: 0.25rem 0;
}

[data-testid="stSidebar"] { background: #0b1018; border-right: 1px solid #1c2738; }

div[data-testid="stMetricValue"] { font-family: 'IBM Plex Mono', monospace; }
</style>
"""


def inject_styles() -> None:
    import streamlit as st

    st.markdown(HF_CSS, unsafe_allow_html=True)


def action_class(action: str) -> str:
    return {
        "BUY": "action-buy",
        "HOLD": "action-hold",
        "SELL": "action-sell",
        "AVOID": "action-avoid",
    }.get(action or "", "")


def action_color(action: str) -> str:
    return {
        "BUY": "#3dd68c",
        "HOLD": "#f5c842",
        "SELL": "#ff9f43",
        "AVOID": "#ff6b6b",
    }.get(action or "", "#8b9cb3")
