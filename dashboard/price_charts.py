"""Plotly price charts — yfinance OHLC with SMA overlays and analyst target."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

SMA_COLORS = {9: "#a78bfa", 20: "#60a5fa", 50: "#fbbf24", 100: "#fb923c", 200: "#f87171"}


@st.cache_data(ttl=300, show_spinner=False)
def fetch_price_history(ticker: str, period: str = "6mo") -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError:
        return pd.DataFrame()

    try:
        raw = yf.download(ticker, period=period, progress=False, auto_adjust=True, threads=False)
    except Exception:
        return pd.DataFrame()

    if raw is None or raw.empty:
        return pd.DataFrame()

    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]) for c in df.columns]
    df = df.reset_index()
    date_col = "Date" if "Date" in df.columns else df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col])
    return df


def _col(df: pd.DataFrame, name: str) -> pd.Series | None:
    for c in df.columns:
        if str(c).lower() == name.lower():
            return df[c]
    return None


def build_price_figure(
    ticker: str,
    df: pd.DataFrame,
    *,
    chart_type: str = "candlestick",
    sma_periods: tuple[int, ...] = (20, 50, 200),
    target_price: float | None = None,
    current_price: float | None = None,
    height: int = 420,
) -> go.Figure:
    fig = go.Figure()
    if df.empty:
        fig.update_layout(title=f"{ticker} — no price data", height=height)
        return fig

    date_col = "Date" if "Date" in df.columns else df.columns[0]
    close = _col(df, "Close")
    if close is None:
        fig.update_layout(title=f"{ticker} — missing Close column", height=height)
        return fig

    x = df[date_col]

    if chart_type == "candlestick":
        o, h, l = _col(df, "Open"), _col(df, "High"), _col(df, "Low")
        if o is not None and h is not None and l is not None:
            fig.add_trace(
                go.Candlestick(
                    x=x,
                    open=o,
                    high=h,
                    low=l,
                    close=close,
                    name=ticker,
                    increasing_line_color="#3dd68c",
                    decreasing_line_color="#ff6b6b",
                )
            )
        else:
            fig.add_trace(go.Scatter(x=x, y=close, mode="lines", name=ticker, line=dict(color="#6ea8fe", width=2)))
    else:
        fig.add_trace(go.Scatter(x=x, y=close, mode="lines", name="Close", line=dict(color="#6ea8fe", width=2)))

    for period in sma_periods:
        if len(close) >= period:
            sma = close.rolling(period).mean()
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=sma,
                    mode="lines",
                    name=f"SMA{period}",
                    line=dict(color=SMA_COLORS.get(period, "#94a3b8"), width=1.2),
                )
            )

    if target_price:
        fig.add_hline(
            y=float(target_price),
            line_dash="dash",
            line_color="#3dd68c",
            annotation_text=f"Target ${target_price:,.2f}",
            annotation_position="right",
        )
    if current_price:
        fig.add_hline(
            y=float(current_price),
            line_dash="dot",
            line_color="#f5c842",
            annotation_text=f"Last ${current_price:,.2f}",
            annotation_position="left",
        )

    fig.update_layout(
        title=f"{ticker} — price & SMAs",
        height=height,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def build_normalized_compare_figure(tickers: list[str], period: str = "6mo", height: int = 320) -> go.Figure:
    fig = go.Figure()
    palette = ["#3dd68c", "#60a5fa", "#fbbf24", "#fb923c", "#a78bfa", "#f472b6", "#34d399", "#f87171"]
    for i, t in enumerate(tickers):
        df = fetch_price_history(t, period)
        close = _col(df, "Close")
        if close is None or close.empty:
            continue
        norm = (close / close.iloc[0] - 1) * 100
        date_col = "Date" if "Date" in df.columns else df.columns[0]
        fig.add_trace(
            go.Scatter(
                x=df[date_col],
                y=norm,
                mode="lines",
                name=t,
                line=dict(color=palette[i % len(palette)], width=2),
            )
        )
    fig.update_layout(
        title="Normalized performance (%)",
        height=height,
        margin=dict(l=10, r=10, t=40, b=10),
        template="plotly_dark",
        yaxis_title="% vs start",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def render_price_chart(
    ticker: str,
    doc: dict | None = None,
    *,
    period: str = "6mo",
    chart_type: str = "candlestick",
    sma_periods: tuple[int, ...] | None = None,
    height: int = 420,
) -> None:
    m = (doc or {}).get("metrics") or {}
    target = m.get("target_price")
    current = m.get("price")
    if sma_periods is None:
        sma_periods = (20, 50, 200)
        if doc and doc.get("sma_period"):
            p = int(doc["sma_period"])
            sma_periods = tuple(sorted(set((*sma_periods, p))))

    df = fetch_price_history(ticker, period)
    if df.empty:
        st.warning(f"Could not load price history for {ticker}. Install yfinance and check your connection.")
        return

    fig = build_price_figure(
        ticker,
        df,
        chart_type=chart_type,
        sma_periods=sma_periods,
        target_price=float(target) if target else None,
        current_price=float(current) if current else None,
        height=height,
    )
    st.plotly_chart(fig, use_container_width=True)
