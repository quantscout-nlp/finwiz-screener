#!/usr/bin/env python3
"""Finwiz Screener for Promising Growth Stocks — Hedge Fund Manager Dashboard."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib_finwiz import (  # noqa: E402
    apply_nl_hints,
    match_doc,
    parse_structured_query,
    rebuild_index,
)
from dashboard.components import filter_docs, render_header, render_kpi_row, render_ticker_card
from dashboard.data_loader import (
    docs_to_rows,
    finviz_hits_url,
    load_deep_dive_md,
    load_ticker_profile,
    read_index,
    read_paper_ledger,
    read_toggles,
    read_url_file,
    write_toggles,
)
from dashboard.llm_rerank import llm_rerank
from dashboard.price_charts import build_normalized_compare_figure, render_price_chart
from dashboard.styles import inject_styles

st.set_page_config(
    page_title="Finwiz Screener | HF Trading Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


def auto_refresh_worker() -> None:
    if not st.session_state.get("auto_refresh"):
        return
    interval = int(st.session_state.get("auto_refresh_sec", 60))
    now = datetime.now()
    last = st.session_state.get("last_auto_refresh_dt")
    if last and (now - last).total_seconds() < interval:
        return
    st.session_state.last_auto_refresh_dt = now
    st.session_state.last_sync = now.strftime("%H:%M:%S")
    refresh_index(sync_elite=True)
    st.rerun()


@st.fragment(run_every=timedelta(seconds=30))
def auto_refresh_tick() -> None:
    auto_refresh_worker()


PAGES = [
    "Command Center",
    "Growth Screener",
    "Capitulation",
    "Ticker Intel",
    "Query Lab",
    "Controls & Export",
    "Paper Trading",
]


@st.cache_data(ttl=120, show_spinner=False)
def cached_index(rebuild: bool = False) -> dict:
    return read_index(force_rebuild=rebuild)


def ensure_state() -> None:
    if "index" not in st.session_state:
        st.session_state.index = cached_index(False)
    if "toggles" not in st.session_state:
        st.session_state.toggles = read_toggles()


def refresh_index(sync_elite: bool = True) -> dict | None:
    elite_result = None
    if sync_elite:
        try:
            sys.path.insert(0, str(SCRIPTS))
            from finviz_elite import sync_if_configured  # noqa: E402

            elite_result = sync_if_configured()
        except Exception as exc:
            elite_result = {"ok": False, "reason": str(exc)}
    cached_index.clear()
    st.session_state.index = read_index(force_rebuild=True)
    st.session_state.toggles = read_toggles()
    st.session_state.last_elite_sync = elite_result
    return elite_result


def sidebar() -> str:
    inject_styles()
    with st.sidebar:
        st.markdown('<div class="sidebar-brand">Finwiz Screener</div>', unsafe_allow_html=True)
        st.caption("Promising Growth Stocks")
        st.divider()
        page = st.radio("Navigate", PAGES, label_visibility="collapsed")
        st.divider()
        idx = st.session_state.index
        toggles = st.session_state.toggles
        st.caption(f"Index: {idx.get('updated')} · {idx.get('count', 0)} names")
        st.markdown("**Screener toggles**")
        sma = dict(toggles.get("sma_filter") or {})
        periods = sma.get("allowed_periods", [9, 20, 50, 100, 200])
        sma_on = st.toggle(
            "SMA filter ON/OFF",
            value=bool(sma.get("enabled", True)),
            key="sidebar_sma_on",
            help="When ON, BUY requires price above selected SMA",
        )
        _cur_period = sma.get("period", 200)
        if _cur_period not in periods:
            _cur_period = 200
        sma_period_sel = st.selectbox(
            "SMA period",
            periods,
            index=periods.index(_cur_period),
            key="sidebar_sma_period",
        )
        tight_on = st.toggle(
            "Tight BUY ON/OFF",
            value=bool(toggles.get("tight_buy", {}).get("enabled", True)),
            key="sidebar_tight_on",
        )
        cap_on = st.toggle(
            "Capitulation mode",
            value=bool(toggles.get("capitulation_mode", {}).get("enabled", True)),
            key="sidebar_cap_on",
        )
        if st.button("Apply toggles & rebuild", use_container_width=True, type="primary"):
            new_t = dict(toggles)
            new_t.setdefault("sma_filter", {})["enabled"] = sma_on
            new_t["sma_filter"]["period"] = int(sma_period_sel)
            new_t.setdefault("tight_buy", {})["enabled"] = tight_on
            new_t.setdefault("capitulation_mode", {})["enabled"] = cap_on
            write_toggles(new_t)
            refresh_index(sync_elite=True)
            st.session_state.toggles = read_toggles()
            st.session_state.last_sync = datetime.now().strftime("%H:%M:%S")
            st.rerun()
        st.caption(
            f"Active: SMA{sma_period_sel} {'ON' if sma_on else 'OFF'}"
            f" · Tight {'ON' if tight_on else 'OFF'}"
        )
        try:
            sys.path.insert(0, str(SCRIPTS))
            from finviz_elite import elite_configured  # noqa: E402

            elite_on = elite_configured()
        except Exception:
            elite_on = False
        st.caption(f"Finviz Elite: {'connected' if elite_on else 'not configured'}")
        openai_on = bool(
            (os.environ.get("OPENAI_API_KEY") or "").strip()
            or (os.environ.get("FINWIZ_LLM_API_KEY") or "").strip()
        )
        st.caption(f"OpenAI LLM: {'ready' if openai_on else 'not set'}")
        if not elite_on or not openai_on:
            st.caption("Restart dashboard via launch_dashboard.ps1 after setting User env vars.")
        if st.button("Rebuild index", use_container_width=True):
            refresh_index()
            st.session_state.last_sync = datetime.now().strftime("%H:%M:%S")
            st.rerun()
        st.divider()
        st.session_state.auto_refresh = st.toggle(
            "Live auto-refresh",
            value=st.session_state.get("auto_refresh", False),
            help="Rebuild index on a timer (full screener rescore)",
        )
        if st.session_state.auto_refresh:
            _refresh_opts = [30, 60, 120, 300]
            _cur = st.session_state.get("auto_refresh_sec", 60)
            _idx = _refresh_opts.index(_cur) if _cur in _refresh_opts else 1
            st.session_state.auto_refresh_sec = st.selectbox(
                "Refresh interval",
                _refresh_opts,
                index=_idx,
                format_func=lambda s: f"{s}s",
            )
            st.caption(f"Last sync: {st.session_state.get('last_sync', '—')}")
            auto_refresh_tick()
        st.divider()
        st.caption("Data: Finviz Elite sync + yfinance charts")
    return page


def page_command_center() -> None:
    idx = st.session_state.index
    docs = idx.get("docs", [])
    toggles = st.session_state.toggles
    sma_period = toggles.get("sma_filter", {}).get("period", 200)

    render_header(
        "Command Center",
        "Portfolio-level view of Finwiz growth ranks, gate status, and capitulation overlay.",
    )

    buys = [d for d in docs if d.get("action") == "BUY"]
    holds = [d for d in docs if d.get("action") == "HOLD"]
    gated = [d for d in docs if d.get("passes_gate")]
    caps = [d for d in docs if d.get("capitulation_pass")]
    avg_comp = round(sum((d.get("scores") or {}).get("composite", 0) for d in docs) / max(len(docs), 1), 1)
    avg_upside = round(sum(d.get("upside_pct") or 0 for d in buys) / max(len(buys), 1), 1) if buys else 0

    render_kpi_row(
        [
            ("BUY", str(len(buys)), f"{len(buys)} actionable"),
            ("HOLD", str(len(holds)), "watchlist"),
            ("Gate PASS", str(len(gated)), f"of {len(docs)}"),
            ("Capitulation", str(len(caps)), "mean-reversion hits"),
            ("Avg Composite", str(avg_comp), f"BUY avg upside {avg_upside}%"),
        ]
    )

    c1, c2 = st.columns(2)
    with c1:
        action_counts = pd.Series([d.get("action") for d in docs]).value_counts().reset_index()
        action_counts.columns = ["Action", "Count"]
        fig = px.pie(
            action_counts,
            names="Action",
            values="Count",
            color="Action",
            color_discrete_map={
                "BUY": "#3dd68c",
                "HOLD": "#f5c842",
                "SELL": "#ff9f43",
                "AVOID": "#ff6b6b",
            },
            hole=0.45,
        )
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=320, showlegend=True, title="Action mix")
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        scatter = pd.DataFrame(
            [
                {
                    "Ticker": d["ticker"],
                    "Composite": (d.get("scores") or {}).get("composite"),
                    "Upside %": d.get("upside_pct"),
                    "Action": d.get("action"),
                    "RSI": (d.get("technicals") or {}).get("rsi14"),
                }
                for d in docs
            ]
        )
        fig2 = px.scatter(
            scatter,
            x="Composite",
            y="Upside %",
            color="Action",
            hover_name="Ticker",
            size="RSI",
            color_discrete_map={
                "BUY": "#3dd68c",
                "HOLD": "#f5c842",
                "SELL": "#ff9f43",
                "AVOID": "#ff6b6b",
            },
        )
        fig2.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=320, title="Composite vs upside")
        st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Top BUY — ranked")
    buy_tickers = [d["ticker"] for d in buys]
    if buy_tickers:
        with st.expander("BUY basket — normalized price performance", expanded=False):
            st.plotly_chart(build_normalized_compare_figure(buy_tickers, "6mo"), use_container_width=True)
    for d in sorted(buys, key=lambda x: (x.get("scores") or {}).get("composite", 0), reverse=True):
        render_ticker_card(d, sma_period)


def page_growth_screener() -> None:
    idx = st.session_state.index
    docs = idx.get("docs", [])
    toggles = st.session_state.toggles
    sma_period = toggles.get("sma_filter", {}).get("period", 200)

    render_header("Growth Screener", "Interactive table mirroring CLI query output — filter, sort, drill down.")

    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        action_filter = st.multiselect("Action", ["BUY", "HOLD", "SELL", "AVOID"], default=["BUY", "HOLD"])
    with fc2:
        gate_only = st.checkbox("Gate PASS only", value=False)
    with fc3:
        min_comp = st.slider("Min composite", 0, 100, 65)
    with fc4:
        search = st.text_input("Search ticker / company / tags")

    filtered = filter_docs(docs, actions=action_filter or None, gate_only=gate_only, min_composite=min_comp, search=search)
    rows = docs_to_rows({"docs": filtered})
    if not rows:
        st.info("No matches for current filters.")
        return

    df = pd.DataFrame([{k: v for k, v in r.items() if k != "_raw"} for r in rows])
    sma_col = f"SMA{sma_period} %"
    display_cols = [
        "Ticker",
        "Company",
        "Action",
        "Analyst",
        "Recom",
        "Upside %",
        "Composite",
        "Gate",
        "News Flow",
        "Technicals",
        "RSI",
        sma_col if sma_col in df.columns else "SMA200 %",
        "Capitulation",
        "Price",
        "Sales YoY %",
        "PEG",
    ]
    display_cols = [c for c in display_cols if c in df.columns]
    st.dataframe(
        df[display_cols].sort_values(["Action", "Composite"], ascending=[True, False]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Upside %": st.column_config.NumberColumn(format="%.1f%%"),
            "Composite": st.column_config.ProgressColumn(min_value=0, max_value=100),
            "RSI": st.column_config.NumberColumn(format="%.1f"),
            "Recom": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    buy_tickers = [r["Ticker"] for r in rows if r["Action"] == "BUY"]
    if buy_tickers:
        st.link_button("Finviz — BUY hits", finviz_hits_url(buy_tickers))

    st.subheader("Detail cards")
    selected = st.selectbox("Inspect ticker", [r["Ticker"] for r in rows])
    doc = next(r["_raw"] for r in rows if r["Ticker"] == selected)
    render_ticker_card(doc, sma_period)
    with st.expander("Price chart", expanded=True):
        pc1, pc2 = st.columns(2)
        with pc1:
            period = st.selectbox("History", ["3mo", "6mo", "1y", "2y"], index=1, key="gs_period")
        with pc2:
            ctype = st.selectbox("Chart", ["candlestick", "line"], key="gs_chart")
        render_price_chart(selected, doc, period=period, chart_type=ctype)
    with st.expander("Full reasons & news"):
        st.write(doc.get("action_reasons"))
        st.json(doc.get("news"))


def page_capitulation() -> None:
    idx = st.session_state.index
    docs = idx.get("docs", [])
    caps = [d for d in docs if d.get("capitulation_pass")]
    toggles = st.session_state.toggles.get("capitulation_mode", {})

    render_header(
        "Capitulation / Mean Reversion",
        toggles.get("label", "Second screener — oversold quality names with 5–50% drawdown."),
    )

    if not caps:
        st.warning("No capitulation hits under current config.")
    else:
        cap_df = pd.DataFrame(
            [
                {
                    "Ticker": d["ticker"],
                    "Action": d.get("action"),
                    "Cap Score": (d.get("capitulation") or {}).get("score"),
                    "DD 30d %": (d.get("capitulation") or {}).get("drawdown_30d_pct"),
                    "DD 90d %": (d.get("capitulation") or {}).get("drawdown_90d_pct"),
                    "RSI": (d.get("technicals") or {}).get("rsi14"),
                    "Recom": d.get("recom"),
                    "Composite": (d.get("scores") or {}).get("composite"),
                }
                for d in caps
            ]
        ).sort_values("Cap Score", ascending=False)
        st.dataframe(cap_df, use_container_width=True, hide_index=True)

        fig = go.Figure()
        for d in caps:
            c = d.get("capitulation") or {}
            fig.add_trace(
                go.Bar(
                    name=d["ticker"],
                    x=["30d DD", "90d DD"],
                    y=[c.get("drawdown_30d_pct"), c.get("drawdown_90d_pct")],
                )
            )
        fig.update_layout(barmode="group", height=320, title="Drawdown windows", margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

        tickers = [d["ticker"] for d in caps]
        url = read_url_file("finwiz-capitulation-hits.url.txt") or finviz_hits_url(tickers)
        st.link_button("Finviz — capitulation hits", url)

        for d in caps:
            render_ticker_card(d, st.session_state.toggles.get("sma_filter", {}).get("period", 200))
            cap = d.get("capitulation") or {}
            if cap.get("reasons"):
                st.caption("Capitulation reasons: " + " · ".join(cap["reasons"]))


def page_ticker_intel() -> None:
    idx = st.session_state.index
    docs = idx.get("docs", [])
    tickers = sorted(d["ticker"] for d in docs)

    render_header("Ticker Intel", "Full profile card, metrics, and linked deep-dive research notes.")

    ticker = st.selectbox("Select ticker", tickers)
    doc = next(d for d in docs if d["ticker"] == ticker)
    profile = load_ticker_profile(ticker) or {}
    sma_period = st.session_state.toggles.get("sma_filter", {}).get("period", 200)

    render_ticker_card(doc, sma_period)

    m1, m2, m3, m4 = st.columns(4)
    m = doc.get("metrics") or {}
    t = doc.get("technicals") or {}
    s = doc.get("scores") or {}
    m1.metric("Price", f"${m.get('price', '—')}")
    m2.metric("Target upside", f"{doc.get('upside_pct', '—')}%")
    m3.metric("Composite", s.get("composite", "—"))
    m4.metric("RSI(14)", t.get("rsi14", "—"))

    st.markdown("**Price chart**")
    tc1, tc2, tc3 = st.columns(3)
    with tc1:
        period = st.selectbox("History", ["3mo", "6mo", "1y", "2y"], index=1, key="ti_period")
    with tc2:
        ctype = st.selectbox("Chart type", ["candlestick", "line"], key="ti_chart")
    with tc3:
        show_smas = st.multiselect("SMA overlays", [9, 20, 50, 100, 200], default=[20, 50, 200], key="ti_smas")
    render_price_chart(
        ticker,
        doc,
        period=period,
        chart_type=ctype,
        sma_periods=tuple(sorted(show_smas)) if show_smas else (20, 50, 200),
    )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Fundamentals**")
        st.json(m)
    with c2:
        st.markdown("**Technicals & scores**")
        st.json({"technicals": t, "scores": s, "capitulation": doc.get("capitulation")})

    news = profile.get("news") or doc.get("news") or {}
    if news.get("headline_bullets"):
        st.markdown("**News flow**")
        for b in news["headline_bullets"]:
            st.markdown(f"- {b}")

    md = load_deep_dive_md(ticker, doc)
    if md:
        st.markdown("**Deep dive notes**")
        st.markdown(md)
    elif profile.get("deep_dive", {}).get("included_reason"):
        st.info(profile["deep_dive"]["included_reason"])


def page_query_lab() -> None:
    idx = st.session_state.index
    docs = idx.get("docs", [])

    render_header(
        "Query Lab",
        'Natural-language or structured queries — same engine as `scripts/query.py`.',
    )

    default_q = "growth stocks with strong news and workable technicals"
    query = st.text_input("Query", value=default_q)
    limit = st.slider("Result limit", 1, len(docs), min(8, len(docs)))

    qc1, qc2, qc3 = st.columns(3)
    with qc1:
        use_llm = st.checkbox("LLM rerank", value=st.session_state.get("use_llm", False))
        st.session_state.use_llm = use_llm
    with qc2:
        llm_model = st.selectbox(
            "Model",
            ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
            index=0,
            disabled=not use_llm,
        )
    with qc3:
        api_key_input = st.text_input(
            "OpenAI API key",
            type="password",
            placeholder="Or set OPENAI_API_KEY env var",
            disabled=not use_llm,
            help="Used only in this session; not saved to disk.",
        )

    if st.button("Run query", type="primary"):
        clauses = parse_structured_query(query) + apply_nl_hints(query)
        seen: set[str] = set()
        uniq: list = []
        for c in clauses:
            if c[0] in seen:
                continue
            seen.add(c[0])
            uniq.append(c)
        filtered = [d for d in docs if match_doc(d, uniq, query)]
        if not filtered and uniq:
            filtered = [d for d in docs if match_doc(d, [], query)]
        filtered.sort(
            key=lambda d: (d.get("action_rank", 0), (d.get("scores") or {}).get("composite", 0)),
            reverse=True,
        )
        hits = filtered[:limit]
        st.session_state.llm_rerank_note = None
        if use_llm and hits:
            reranked, err = llm_rerank(hits, query, api_key=api_key_input or None, model=llm_model)
            if err:
                st.session_state.llm_rerank_note = err
            elif reranked:
                hits = reranked
                st.session_state.llm_rerank_note = f"LLM reranked ({llm_model})"
        st.session_state.query_hits = hits
        st.session_state.last_query = query

    if "query_hits" in st.session_state:
        hits = st.session_state.query_hits
        note = st.session_state.get("llm_rerank_note")
        if note and note.startswith("LLM"):
            st.success(f"{len(hits)} matches (LLM reranked) for: {st.session_state.get('last_query', query)}")
        elif note:
            st.warning(f"{len(hits)} matches — {note}")
        else:
            st.success(f"{len(hits)} matches for: {st.session_state.get('last_query', query)}")
        sma_period = st.session_state.toggles.get("sma_filter", {}).get("period", 200)
        for d in hits:
            render_ticker_card(d, sma_period)
            with st.expander(f"{d['ticker']} price chart"):
                render_price_chart(d["ticker"], d, period="6mo")


def page_controls() -> None:
    toggles = dict(st.session_state.toggles)

    render_header(
        "Controls & Export",
        "SMA / Tight BUY toggles (also in sidebar), Finviz Elite sync, automation, and exports.",
    )

    st.markdown("**Master switches (same as sidebar)**")
    c1, c2 = st.columns(2)
    with c1:
        toggles["screener_enabled"] = st.toggle("Screener enabled", toggles.get("screener_enabled", True), key="ctl_screener")
        toggles.setdefault("growth_mode", {})["enabled"] = st.toggle(
            "Growth mode", toggles.get("growth_mode", {}).get("enabled", True), key="ctl_growth"
        )
        toggles.setdefault("capitulation_mode", {})["enabled"] = st.toggle(
            "Capitulation mode", toggles.get("capitulation_mode", {}).get("enabled", True), key="ctl_cap"
        )
    with c2:
        sma = toggles.setdefault("sma_filter", {})
        sma["enabled"] = st.toggle("SMA filter ON/OFF", sma.get("enabled", True), key="ctl_sma")
        periods = sma.get("allowed_periods", [9, 20, 50, 100, 200])
        _p = sma.get("period", 200)
        sma["period"] = st.selectbox(
            "SMA period (9 / 20 / 50 / 100 / 200)",
            periods,
            index=periods.index(_p) if _p in periods else periods.index(200),
            key="ctl_sma_period",
        )
        tight = toggles.setdefault("tight_buy", {})
        tight["enabled"] = st.toggle("Tight BUY ON/OFF", tight.get("enabled", True), key="ctl_tight")

    if st.button("Save toggles & rebuild", type="primary"):
        write_toggles(toggles)
        refresh_index(sync_elite=True)
        st.success("Toggles saved and index rebuilt.")
        st.rerun()

    st.divider()
    st.markdown("**Finviz Elite live sync**")
    if st.button("Sync Elite quotes now", use_container_width=True):
        result = refresh_index(sync_elite=True)
        if result and result.get("ok"):
            st.success(f"Synced {result.get('count', 0)} tickers from Finviz Elite.")
        elif result:
            st.error(result.get("reason", "Elite sync failed"))
        else:
            st.warning("FINVIZ_API_KEY not set — add your Elite API token to Windows environment variables.")
        st.rerun()

    last_elite = st.session_state.get("last_elite_sync")
    if last_elite:
        st.caption(f"Last Elite sync: {last_elite}")

    st.divider()
    st.markdown("**Automation (always-on)**")
    st.code(
        "py -3 scripts\\install_scheduled_task.ps1\n"
        "py -3 scripts\\automation_cycle.py --deep-dives\n"
        "py -3 scripts\\auto_add_tickers.py --tickers AMD,ARM --status candidate\n"
        "py -3 scripts\\auto_deep_dive.py --all-core",
        language="powershell",
    )
    ac1, ac2 = st.columns(2)
    with ac1:
        if st.button("Run automation cycle now"):
            import subprocess

            r = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "automation_cycle.py"), "--deep-dives"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            st.code(r.stdout or r.stderr)
            refresh_index(sync_elite=False)
            st.rerun()
    with ac2:
        add_sym = st.text_input("Auto-add tickers (comma-separated)", placeholder="AMD,ARM,ASML")
        if st.button("Add candidates to watchlist") and add_sym.strip():
            import subprocess

            r = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "auto_add_tickers.py"),
                    "--tickers",
                    add_sym,
                    "--status",
                    "candidate",
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            st.code(r.stdout or r.stderr)
            refresh_index(sync_elite=False)
            st.rerun()

    st.divider()
    st.markdown("**Finviz export URLs (your screened tickers)**")
    for fname, label in [
        ("finviz-buy-hits.url.txt", "BUY hits"),
        ("finwiz-capitulation-hits.url.txt", "Capitulation hits"),
        ("finwiz-gate-hits.url.txt", "Gate PASS hits"),
        ("finwiz-hold-hits.url.txt", "HOLD hits"),
    ]:
        url = read_url_file(fname)
        if url:
            st.link_button(label, url)

    st.divider()
    with st.expander("Raw toggles.json"):
        st.json(toggles)
    with st.expander("Raw search_index.json (summary)"):
        idx = st.session_state.index
        st.json({"updated": idx.get("updated"), "count": idx.get("count"), "toggles": idx.get("toggles")})


def page_paper() -> None:
    render_header(
        "Paper Trading",
        "Simulated fills into bot/ledger/paper_ledger.json — no live broker orders.",
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Run paper cycle (LIVE paper fills)", type="primary"):
            import subprocess

            r = subprocess.run(
                [sys.executable, str(ROOT / "bot" / "run_paper.py")],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            st.code(r.stdout or r.stderr)
            st.rerun()
    with c2:
        if st.button("Dry-run (no ledger write)"):
            import subprocess

            r = subprocess.run(
                [sys.executable, str(ROOT / "bot" / "run_paper.py"), "--dry-run"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            st.code(r.stdout or r.stderr)
    with c3:
        if st.button("Full automation cycle"):
            import subprocess

            r = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "automation_cycle.py"), "--deep-dives"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            st.code(r.stdout or r.stderr)
            st.rerun()

    ledger = read_paper_ledger()
    if not ledger:
        st.info("No paper ledger yet — click **Run paper cycle** above.")
        return

    m1, m2, m3 = st.columns(3)
    m1.metric("Cash", f"${ledger.get('cash', 0):,.2f}")
    m2.metric("Positions", str(len(ledger.get("positions") or {})))
    m3.metric("Halted", "YES" if ledger.get("halted") else "no")
    positions = ledger.get("positions") or {}
    if positions:
        rows = [{"Ticker": k, **v} for k, v in positions.items()]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    trades = ledger.get("trades") or []
    if trades:
        st.subheader("Recent trades")
        st.dataframe(pd.DataFrame(trades[::-1][:50]), use_container_width=True, hide_index=True)
    with st.expander("Raw ledger JSON"):
        st.json(ledger)


def main() -> None:
    ensure_state()
    page = sidebar()
    routes = {
        "Command Center": page_command_center,
        "Growth Screener": page_growth_screener,
        "Capitulation": page_capitulation,
        "Ticker Intel": page_ticker_intel,
        "Query Lab": page_query_lab,
        "Controls & Export": page_controls,
        "Paper Trading": page_paper,
    }
    routes[page]()


if __name__ == "__main__":
    main()
