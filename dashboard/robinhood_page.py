"""Robinhood Watchlist dashboard page — RH positions + Finwiz enrichment."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.components import render_header, render_kpi_row
from dashboard.data_loader import load_ticker_profile
from dashboard.price_charts import render_price_chart

ROOT = Path(__file__).resolve().parents[1]
RH_POSITIONS = ROOT / "data" / "robinhood" / "positions.json"
RH_CSV = ROOT / "data" / "robinhood" / "positions.csv"
ASSISTANT_SRC = Path(
    r"D:\Finwiz Screener Stocks Trading Assistant\Robinhood.com Trading Watchlist\NEW_Robinhood_com_Trading_Watchlist.json"
)


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@st.cache_data(ttl=120, show_spinner=False)
def load_rh_positions() -> list[dict]:
    for path in (RH_POSITIONS, ASSISTANT_SRC):
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    return []


@st.cache_data(ttl=600, show_spinner=False)
def fetch_live_intel(ticker: str) -> dict:
    """Live snapshot: technicals from Alpaca→yfinance bars; fundamentals/news/analyst via yfinance."""
    out: dict = {
        "ok": False,
        "company": None,
        "sector": None,
        "industry": None,
        "metrics": {},
        "technicals": {},
        "analyst": {},
        "news": [],
        "bars_provider": None,
        "error": None,
    }

    tech: dict = {}
    bars_provider = None
    try:
        import sys
        from pathlib import Path

        scripts = Path(__file__).resolve().parents[1] / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from lib_market_data import fetch_dashboard_bars

        hist, bars_provider = fetch_dashboard_bars(ticker, lookback_days=420)
        out["bars_provider"] = bars_provider
        if hist is not None and not hist.empty and "Close" in hist.columns:
            close = hist["Close"].dropna()
            if len(close) >= 15:
                delta = close.diff()
                gain = delta.clip(lower=0).rolling(14).mean()
                loss = (-delta.clip(upper=0)).rolling(14).mean()
                rs = gain / loss.replace(0, pd.NA)
                rsi = 100 - (100 / (1 + rs))
                tech["rsi14"] = round(float(rsi.iloc[-1]), 2) if pd.notna(rsi.iloc[-1]) else None
            last = float(close.iloc[-1])
            for n, key in ((20, "sma20_pct"), (50, "sma50_pct"), (200, "sma200_pct")):
                if len(close) >= n:
                    sma = float(close.rolling(n).mean().iloc[-1])
                    tech[key] = round((last / sma - 1) * 100, 2) if sma else None
            if len(close) >= 63:
                tech["perf_quarter"] = round((last / float(close.iloc[-63]) - 1) * 100, 2)
            if len(close) >= 21:
                tech["perf_month"] = round((last / float(close.iloc[-21]) - 1) * 100, 2)
            if "Date" in hist.columns:
                dates = pd.to_datetime(hist["Date"])
                ytd_mask = dates.dt.year == dates.iloc[-1].year
                ytd_close = close.loc[ytd_mask.values] if hasattr(ytd_mask, "values") else close[ytd_mask]
                if len(ytd_close) >= 2:
                    tech["perf_ytd"] = round((float(ytd_close.iloc[-1]) / float(ytd_close.iloc[0]) - 1) * 100, 2)
            else:
                # index may already be datetime
                try:
                    idx = close.index
                    ytd = close[idx.year == idx[-1].year]
                    if len(ytd) >= 2:
                        tech["perf_ytd"] = round((float(ytd.iloc[-1]) / float(ytd.iloc[0]) - 1) * 100, 2)
                except Exception:
                    pass
            hi = float(close.max())
            tech["from_52w_high_pct"] = round((last / hi - 1) * 100, 2) if hi else None
            tech["price_last"] = last
    except Exception as exc:
        out["error"] = f"bars: {exc}"

    try:
        import yfinance as yf
    except ImportError:
        out["technicals"] = {k: v for k, v in tech.items() if v is not None}
        out["ok"] = bool(tech)
        if not out.get("error"):
            out["error"] = "yfinance not installed (fundamentals/news unavailable)"
        return out

    try:
        t = yf.Ticker(ticker)
        info = {}
        try:
            info = t.info or {}
        except Exception:
            info = {}

        # If Alpaca bars failed, fall back to yfinance history for technicals
        if not tech:
            hist = t.history(period="1y", auto_adjust=True)
            bars_provider = "yfinance"
            out["bars_provider"] = bars_provider
            if hist is not None and not hist.empty and "Close" in hist.columns:
                close = hist["Close"].dropna()
                if len(close) >= 15:
                    delta = close.diff()
                    gain = delta.clip(lower=0).rolling(14).mean()
                    loss = (-delta.clip(upper=0)).rolling(14).mean()
                    rs = gain / loss.replace(0, pd.NA)
                    rsi = 100 - (100 / (1 + rs))
                    tech["rsi14"] = round(float(rsi.iloc[-1]), 2) if pd.notna(rsi.iloc[-1]) else None
                last = float(close.iloc[-1])
                for n, key in ((20, "sma20_pct"), (50, "sma50_pct"), (200, "sma200_pct")):
                    if len(close) >= n:
                        sma = float(close.rolling(n).mean().iloc[-1])
                        tech[key] = round((last / sma - 1) * 100, 2) if sma else None
                if len(close) >= 63:
                    tech["perf_quarter"] = round((last / float(close.iloc[-63]) - 1) * 100, 2)
                if len(close) >= 21:
                    tech["perf_month"] = round((last / float(close.iloc[-21]) - 1) * 100, 2)
                ytd = close[close.index.year == close.index[-1].year]
                if len(ytd) >= 2:
                    tech["perf_ytd"] = round((float(ytd.iloc[-1]) / float(ytd.iloc[0]) - 1) * 100, 2)
                hi = float(close.max())
                tech["from_52w_high_pct"] = round((last / hi - 1) * 100, 2) if hi else None

        metrics = {
            "price": info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
            or tech.get("price_last"),
            "market_cap": (info.get("marketCap") / 1e6) if info.get("marketCap") else None,
            "forward_pe": info.get("forwardPE"),
            "pe": info.get("trailingPE"),
            "peg": info.get("pegRatio"),
            "gross_margin": (info.get("grossMargins") * 100) if info.get("grossMargins") is not None else None,
            "profit_margin": (info.get("profitMargins") * 100) if info.get("profitMargins") is not None else None,
            "debt_equity": info.get("debtToEquity"),
            "sales_growth_yoy": (info.get("revenueGrowth") * 100) if info.get("revenueGrowth") is not None else None,
            "eps_growth_yoy": (info.get("earningsGrowth") * 100) if info.get("earningsGrowth") is not None else None,
            "target_price": info.get("targetMeanPrice"),
            "recom": info.get("recommendationMean"),
        }

        analyst = {
            "recommendation": info.get("recommendationKey"),
            "recom_mean": info.get("recommendationMean"),
            "target_mean": info.get("targetMeanPrice"),
            "target_high": info.get("targetHighPrice"),
            "target_low": info.get("targetLowPrice"),
            "num_analysts": info.get("numberOfAnalystOpinions"),
        }
        try:
            rec = t.recommendations
            if rec is not None and not rec.empty:
                analyst["recent_grades"] = rec.tail(8).reset_index().to_dict(orient="records")
        except Exception:
            pass

        news_items = []
        try:
            raw_news = t.news or []
            for item in raw_news[:8]:
                content = item.get("content") if isinstance(item.get("content"), dict) else {}
                title = item.get("title") or content.get("title") or item.get("headline")
                link = item.get("link")
                if not link and isinstance(content.get("canonicalUrl"), dict):
                    link = content.get("canonicalUrl", {}).get("url")
                pub = None
                if isinstance(content.get("provider"), dict):
                    pub = content.get("provider", {}).get("displayName")
                pub = pub or item.get("publisher")
                if title:
                    news_items.append({"title": title, "link": link, "publisher": pub})
        except Exception:
            pass

        out.update(
            {
                "ok": True,
                "company": info.get("shortName") or info.get("longName"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "metrics": {k: v for k, v in metrics.items() if v is not None},
                "technicals": {k: v for k, v in tech.items() if v is not None and k != "price_last"},
                "analyst": analyst,
                "news": news_items,
                "bars_provider": bars_provider or out.get("bars_provider"),
            }
        )
        return out
    except Exception as exc:
        out["technicals"] = {k: v for k, v in tech.items() if v is not None and k != "price_last"}
        out["ok"] = bool(out["technicals"])
        out["error"] = str(exc)
        return out


# Back-compat alias
fetch_yfinance_intel = fetch_live_intel


def analyst_label(recom) -> str:
    try:
        r = float(recom)
    except (TypeError, ValueError):
        return "—"
    if r <= 1.5:
        return "Strong Buy"
    if r <= 2.5:
        return "Buy"
    if r <= 3.5:
        return "Hold"
    if r <= 4.5:
        return "Sell"
    return "Strong Sell"


def build_joined_table(positions: list[dict], index_docs: list[dict]) -> pd.DataFrame:
    by_t = {str(d.get("ticker") or "").upper(): d for d in index_docs}
    rows = []
    for p in positions:
        t = str(p.get("ticker") or "").upper()
        doc = by_t.get(t) or {}
        m = doc.get("metrics") or {}
        tech = doc.get("technicals") or {}
        scores = doc.get("scores") or {}
        news = doc.get("news") or {}
        rows.append(
            {
                "Ticker": t,
                "Shares": _num(p.get("shares")),
                "Avg Cost": _num(p.get("avg_cost")),
                "Trade Amt": _num(p.get("trade_amount_market_value")),
                "Today P/L": _num(p.get("today_pnl")),
                "Today %": _num(p.get("today_pct")),
                "Total Profit": _num(p.get("total_pnl_profit")),
                "Total %": _num(p.get("total_pct_gain")),
                "% DD": _num(p.get("pct_drawdown")),
                "90D %": _num(p.get("pct_rise_90d")),
                "RH Price": _num(p.get("price")),
                "Action": doc.get("action"),
                "Analyst": doc.get("analyst_label") or analyst_label(m.get("recom")),
                "Recom": m.get("recom"),
                "Upside %": doc.get("upside_pct"),
                "Composite": scores.get("composite"),
                "Gate": ("PASS" if doc.get("passes_gate") else ("FAIL" if doc else None)),
                "RSI": tech.get("rsi14"),
                "SMA200 %": tech.get("sma200_pct") if tech.get("sma200_pct") is not None else doc.get("sma_pct"),
                "YTD %": tech.get("perf_ytd"),
                "Sales YoY %": m.get("sales_growth_yoy"),
                "EPS YoY %": m.get("eps_growth_yoy"),
                "PEG": m.get("peg"),
                "Fwd P/E": m.get("forward_pe"),
                "Target": m.get("target_price"),
                "News Flow": doc.get("news_flow"),
                "Catalyst": news.get("next_catalyst"),
                "Company": (
                    None
                    if not doc.get("company") or doc.get("company") == "Company Name"
                    else doc.get("company")
                ),
                "In Finwiz": "yes" if doc else "no",
                "Finviz": doc.get("finviz_url") or f"https://finviz.com/quote.ashx?t={t}",
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty and "Trade Amt" in df.columns:
        df = df.sort_values("Trade Amt", ascending=False, na_position="last")
    return df


def page_robinhood_watchlist() -> None:
    idx = st.session_state.index
    docs = idx.get("docs", [])
    positions = load_rh_positions()

    render_header(
        "Robinhood Watchlist",
        "NEW Robinhood.com Trading Watchlist → Finwiz desk: positions + technicals + fundamentals + news + analyst ratings.",
    )

    if not positions:
        st.warning(
            "No Robinhood positions found. Run:\n\n"
            "`py -3 scripts\\enrich_robinhood_watchlist.py`\n\n"
            f"Expected: `{RH_POSITIONS}`"
        )
        return

    df = build_joined_table(positions, docs)
    in_fw = int((df["In Finwiz"] == "yes").sum()) if not df.empty else 0
    trade_sum = float(df["Trade Amt"].fillna(0).sum()) if not df.empty else 0.0
    tot_pnl = float(df["Total Profit"].fillna(0).sum()) if not df.empty else 0.0
    avg_90 = float(df["90D %"].dropna().mean()) if not df.empty and df["90D %"].notna().any() else None

    render_kpi_row(
        [
            ("Tickers", str(len(df)), f"{in_fw} in Finwiz index"),
            ("Trade amount", f"${trade_sum:,.0f}", "Σ market value"),
            ("Total P/L", f"${tot_pnl:,.0f}", "Σ position total return $"),
            ("Avg 90D %", f"{avg_90:.1f}%" if avg_90 is not None else "—", "mean RH 90D rise"),
            ("Elite / profiles", f"{in_fw}/{len(df)}", "enrich via script for full coverage"),
        ]
    )

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        q = st.text_input("Filter ticker / company", "", key="rh_filter")
    with c2:
        only_fw = st.checkbox("Finwiz-enriched only", value=False, key="rh_only_fw")
    with c3:
        only_pos = st.checkbox("Has trade amount", value=True, key="rh_only_pos")

    view = df.copy()
    if q:
        ql = q.upper()
        view = view[
            view["Ticker"].astype(str).str.upper().str.contains(ql, na=False)
            | view["Company"].astype(str).str.upper().str.contains(ql, na=False)
        ]
    if only_fw:
        view = view[view["In Finwiz"] == "yes"]
    if only_pos:
        view = view[view["Trade Amt"].notna()]

    st.dataframe(
        view.drop(columns=["Finviz"], errors="ignore"),
        use_container_width=True,
        hide_index=True,
        height=420,
    )

    tickers = view["Ticker"].tolist() if not view.empty else df["Ticker"].tolist()
    if not tickers:
        st.info("No rows match filters.")
        return

    selected = st.selectbox("Inspect ticker", tickers, key="rh_ticker")
    row = df[df["Ticker"] == selected].iloc[0].to_dict()
    doc = next((d for d in docs if d.get("ticker") == selected), None)
    profile = load_ticker_profile(selected) or {}

    st.markdown(f"### {selected} — position + research stack")
    p1, p2, p3, p4, p5 = st.columns(5)
    p1.metric("Trade Amt", f"${row['Trade Amt']:,.2f}" if row.get("Trade Amt") is not None else "—")
    p2.metric("Total Profit", f"${row['Total Profit']:,.2f}" if row.get("Total Profit") is not None else "—")
    p3.metric("Total % / DD", f"{row.get('Total %') or '—'}% / {row.get('% DD') or '—'}%")
    p4.metric("90D %", f"{row['90D %']:.2f}%" if row.get("90D %") is not None else "—")
    p5.metric("Finwiz Action", row.get("Action") or "—")

    tabs = st.tabs(["Technicals", "Fundamentals", "Market News", "Analyst Ratings", "Chart"])

    live = fetch_live_intel(selected)
    m = {**(profile.get("metrics") or {}), **((doc or {}).get("metrics") or {}), **(live.get("metrics") or {})}
    tech = {
        **(profile.get("technicals") or {}),
        **((doc or {}).get("technicals") or {}),
        **(live.get("technicals") or {}),
    }
    bars_src = live.get("bars_provider") or "—"

    with tabs[0]:
        st.caption(
            f"Technicals from Finwiz Elite (when enriched) + live bars via **{bars_src}** "
            "(Alpaca → yfinance fallback)."
        )
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("RSI(14)", tech.get("rsi14", "—"))
        k2.metric("vs SMA20", f"{tech.get('sma20_pct', '—')}%")
        k3.metric("vs SMA50", f"{tech.get('sma50_pct', '—')}%")
        k4.metric("vs SMA200", f"{tech.get('sma200_pct', '—')}%")
        k5, k6, k7, k8 = st.columns(4)
        k5.metric("Month %", tech.get("perf_month", "—"))
        k6.metric("Quarter %", tech.get("perf_quarter", "—"))
        k7.metric("YTD %", tech.get("perf_ytd", "—"))
        k8.metric("From 52w high", f"{tech.get('from_52w_high_pct', '—')}%")
        st.json(tech)

    with tabs[1]:
        st.caption("Historical / current fundamentals (Finviz metrics when synced; else yfinance).")
        f1, f2, f3, f4 = st.columns(4)
        f1.metric("Sales YoY %", m.get("sales_growth_yoy", "—"))
        f2.metric("EPS YoY %", m.get("eps_growth_yoy", "—"))
        f3.metric("PEG", m.get("peg", "—"))
        f4.metric("Fwd P/E", m.get("forward_pe", "—"))
        f5, f6, f7, f8 = st.columns(4)
        f5.metric("Gross margin %", m.get("gross_margin", "—"))
        f6.metric("Profit margin %", m.get("profit_margin", "—"))
        f7.metric("D/E", m.get("debt_equity", "—"))
        f8.metric("Mkt cap ($M)", f"{m.get('market_cap'):,.0f}" if isinstance(m.get("market_cap"), (int, float)) else "—")
        if live.get("sector") or live.get("industry"):
            st.caption(f"{live.get('company') or ''} · {live.get('sector') or ''} · {live.get('industry') or ''}")
        st.json(m)

    with tabs[2]:
        st.caption("Market news — Finwiz curated bullets (if any) + live Yahoo headlines.")
        curated = (profile.get("news") or (doc or {}).get("news") or {}).get("headline_bullets") or []
        if curated:
            st.markdown("**Finwiz curated**")
            for b in curated:
                st.markdown(f"- {b}")
        catalyst = (profile.get("news") or (doc or {}).get("news") or {}).get("next_catalyst")
        if catalyst:
            st.info(f"Next catalyst: {catalyst}")
        live_news = live.get("news") or []
        if live_news:
            st.markdown("**Live headlines**")
            for n in live_news:
                title = n.get("title") or ""
                link = n.get("link")
                pub = n.get("publisher") or ""
                if link:
                    st.markdown(f"- [{title}]({link}) — _{pub}_")
                else:
                    st.markdown(f"- {title} — _{pub}_")
        if not curated and not live_news:
            st.write("No news available for this ticker right now.")
            if live.get("error"):
                st.caption(live["error"])

    with tabs[3]:
        st.caption("Analyst ratings — Finwiz recom/target + live yfinance consensus.")
        a = live.get("analyst") or {}
        recom = m.get("recom") if m.get("recom") is not None else a.get("recom_mean")
        target = m.get("target_price") if m.get("target_price") is not None else a.get("target_mean")
        price = m.get("price") or row.get("RH Price")
        upside = None
        if isinstance(target, (int, float)) and isinstance(price, (int, float)) and price:
            upside = round((target / price - 1) * 100, 2)

        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Label", analyst_label(recom))
        a2.metric("Recom (1=SB … 5=SS)", recom if recom is not None else "—")
        a3.metric("Target", f"${target:,.2f}" if isinstance(target, (int, float)) else "—")
        a4.metric("Upside", f"{upside}%" if upside is not None else "—")
        b1, b2, b3 = st.columns(3)
        b1.metric("Consensus key", a.get("recommendation") or "—")
        b2.metric("# analysts", a.get("num_analysts") or "—")
        b3.metric("Target range", f"{a.get('target_low') or '—'} → {a.get('target_high') or '—'}")
        grades = a.get("recent_grades")
        if grades:
            st.markdown("**Recent grade actions**")
            st.dataframe(pd.DataFrame(grades), use_container_width=True, hide_index=True)

    with tabs[4]:
        period = st.selectbox("History", ["3mo", "6mo", "1y", "2y"], index=0, key="rh_period")
        ctype = st.selectbox("Chart", ["candlestick", "line"], key="rh_chart")
        show_smas = st.multiselect("SMA overlays", [9, 20, 50, 100, 200], default=[20, 50, 200], key="rh_smas")
        chart_doc = doc or {"metrics": {"price": row.get("RH Price"), "target_price": target}, "ticker": selected}
        render_price_chart(
            selected,
            chart_doc,
            period=period,
            chart_type=ctype,
            sma_periods=tuple(sorted(show_smas)) if show_smas else (20, 50, 200),
        )

    st.divider()
    st.caption(
        "Research desk only — maps OCR Robinhood positions into Finwiz. "
        "Does not submit broker orders. Enrich registry: "
        "`py -3 scripts\\enrich_robinhood_watchlist.py --sync-elite`"
    )
    st.link_button("Open on Finviz", row.get("Finviz") or f"https://finviz.com/quote.ashx?t={selected}")
