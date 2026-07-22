"""Shared UI helpers for dashboard pages."""

from __future__ import annotations

import streamlit as st

from dashboard.styles import action_class, action_color


def render_header(title: str, subtitle: str = "") -> None:
    st.markdown(f'<div class="finwiz-title">{title}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="finwiz-sub">{subtitle}</div>', unsafe_allow_html=True)


def kpi_card(label: str, value: str, delta: str = "", delta_color: str = "#8b9cb3") -> str:
    delta_html = f'<div class="kpi-delta" style="color:{delta_color}">{delta}</div>' if delta else ""
    return f"""
    <div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        {delta_html}
    </div>
    """


def render_kpi_row(items: list[tuple[str, str, str]]) -> None:
    """Render KPI row with st.metric + caption (avoids delta HTML leak in some Streamlit builds)."""
    cols = st.columns(len(items))
    for col, (label, value, hint) in zip(cols, items):
        with col:
            st.metric(label, value)
            if hint:
                st.caption(hint)


def render_kpi_row_html(cards: list[str]) -> None:
    """Legacy HTML KPI row — prefer render_kpi_row()."""
    st.markdown(f'<div class="kpi-row">{"".join(cards)}</div>', unsafe_allow_html=True)


def render_ticker_card(doc: dict, sma_period: int = 200) -> None:
    action = doc.get("action", "—")
    cls = action_class(action)
    m = doc.get("metrics") or {}
    t = doc.get("technicals") or {}
    s = doc.get("scores") or {}
    cap = doc.get("capitulation") or {}
    news = doc.get("news") or {}
    reasons = doc.get("action_reasons") or []
    cap_flag = "YES" if doc.get("capitulation_pass") else "no"
    sma_pct = doc.get("sma_pct")
    sma_key = f"SMA{sma_period}"

    st.markdown(
        f"""
        <div class="ticker-card">
            <div class="ticker-head">{doc.get("ticker")} — {doc.get("company")}</div>
            <div class="ticker-meta">
                <span class="{cls}">ACTION: {action}</span>
                &nbsp;|&nbsp; Analyst: {doc.get("analyst_label")} ({doc.get("recom")})
                &nbsp;|&nbsp; Upside: {doc.get("upside_pct")}%
            </div>
            <div class="ticker-meta">
                Status: {doc.get("status")} &nbsp;|&nbsp; Gate: {"PASS" if doc.get("passes_gate") else "FAIL"}
                &nbsp;|&nbsp; Composite: {s.get("composite")} &nbsp;|&nbsp; {sma_key}: {sma_pct}%
            </div>
            <div class="ticker-meta">
                Capitulation: {cap_flag} (dd 30d {cap.get("drawdown_30d_pct")}% / 90d {cap.get("drawdown_90d_pct")}%)
            </div>
            <div class="ticker-meta">
                Deep-dive: news_flow={doc.get("news_flow")} &nbsp;|&nbsp; technicals={doc.get("technicals_label")}
            </div>
            <div class="ticker-meta">
                Sales YoY {m.get("sales_growth_yoy")}% &nbsp;|&nbsp; EPS YoY {m.get("eps_growth_yoy")}%
                &nbsp;|&nbsp; PEG {m.get("peg")} &nbsp;|&nbsp; Fwd P/E {m.get("forward_pe")}
            </div>
            <div class="ticker-meta">
                RSI {t.get("rsi14")} &nbsp;|&nbsp; YTD {t.get("perf_ytd")}% &nbsp;|&nbsp; {t.get("setup", "")}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if reasons:
        pills = "".join(f'<span class="reason-pill">{r}</span>' for r in reasons)
        st.markdown(f"<div>{pills}</div>", unsafe_allow_html=True)

    catalyst = news.get("next_catalyst")
    if catalyst:
        st.caption(f"Catalyst: {catalyst} ({news.get('catalyst_date', 'TBD')})")

    url = doc.get("finviz_url")
    if url:
        st.link_button("Open Finviz", url, use_container_width=False)


def filter_docs(
    docs: list[dict],
    actions: list[str] | None = None,
    gate_only: bool = False,
    capitulation_only: bool = False,
    min_composite: float = 0,
    search: str = "",
) -> list[dict]:
    out = docs
    if actions:
        out = [d for d in out if d.get("action") in actions]
    if gate_only:
        out = [d for d in out if d.get("passes_gate")]
    if capitulation_only:
        out = [d for d in out if d.get("capitulation_pass")]
    if min_composite > 0:
        out = [d for d in out if (d.get("scores") or {}).get("composite", 0) >= min_composite]
    if search.strip():
        q = search.lower()
        out = [
            d
            for d in out
            if q in (d.get("blob") or "").lower()
            or q in d.get("ticker", "").lower()
            or q in (d.get("company") or "").lower()
        ]
    return out
