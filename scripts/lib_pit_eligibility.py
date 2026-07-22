"""Point-in-time eligibility from Massive financials + Benzinga/Massive analyst ratings.

Approximates Finwiz Tight BUY fundamentals historically:
- recom score from Benzinga ratings (via Massive /benzinga/v1/ratings)
- upside from price vs consensus price target
- growth proxies from Massive income statements (sales/EPS YoY when available)
- LeanData fundamentals_latest / statements as offline fallback
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

from lib_market_data import _env

RATING_TO_RECOM = {
    "strong buy": 1.0,
    "strong_buy": 1.0,
    "buy": 1.5,
    "outperform": 1.5,
    "overweight": 1.7,
    "accumulate": 1.7,
    "positive": 1.8,
    "speculative buy": 1.8,
    "hold": 3.0,
    "neutral": 3.0,
    "equal-weight": 3.0,
    "equal weight": 3.0,
    "market perform": 3.0,
    "peer perform": 3.0,
    "sector perform": 3.0,
    "underperform": 4.0,
    "underweight": 4.0,
    "reduce": 4.0,
    "sell": 4.5,
    "strong sell": 5.0,
    "strong_sell": 5.0,
}


def _http_json(url: str, headers: dict[str, str] | None = None, timeout: int = 60) -> Any:
    req = Request(url, headers=headers or {"User-Agent": "FinwizScreener/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _massive_base() -> str:
    return _env("MASSIVE_REST_BASE_URL", "MASSIVE_BASE_URL", "POLYGON_BASE_URL", default="https://api.massive.com").rstrip("/")


def _massive_key() -> str:
    return _env("MASSIVE_API_KEY", "POLYGON_API_KEY")


def rating_to_recom(label: str | None) -> float | None:
    if not label:
        return None
    return RATING_TO_RECOM.get(str(label).strip().lower())


def fetch_benzinga_ratings_massive(ticker: str, start: str, end: str | None = None) -> pd.DataFrame:
    """Historical analyst ratings via Massive Benzinga partner API."""
    key = _massive_key()
    if not key:
        return pd.DataFrame()
    base = _massive_base()
    end = end or date.today().isoformat()
    rows: list[dict] = []
    url = (
        f"{base}/benzinga/v1/ratings?ticker={ticker.upper()}"
        f"&date.gte={start}&date.lte={end}&limit=1000&sort=date.asc&apiKey={key}"
    )
    for _ in range(50):
        try:
            payload = _http_json(url)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            break
        for r in payload.get("results") or []:
            rows.append(
                {
                    "date": r.get("date"),
                    "rating": r.get("rating"),
                    "rating_action": r.get("rating_action"),
                    "price_target": r.get("adjusted_price_target") or r.get("price_target"),
                    "firm": r.get("firm"),
                    "recom": rating_to_recom(r.get("rating")),
                }
            )
        nxt = payload.get("next_url")
        if not nxt:
            break
        url = nxt if "apiKey=" in nxt else (nxt + ("&" if "?" in nxt else "?") + f"apiKey={key}")
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    return df.reset_index(drop=True)


def fetch_massive_income_annual(ticker: str) -> pd.DataFrame:
    key = _massive_key()
    if not key:
        return pd.DataFrame()
    base = _massive_base()
    url = (
        f"{base}/stocks/financials/v1/income-statements?ticker={ticker.upper()}"
        f"&timeframe=annual&limit=100&apiKey={key}"
    )
    try:
        payload = _http_json(url)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return pd.DataFrame()
    results = payload.get("results") or []
    if not results:
        return pd.DataFrame()
    rows = []
    for r in results:
        # field names vary slightly across Massive versions
        rows.append(
            {
                "period_end": r.get("end_date") or r.get("period_end") or r.get("filing_date") or r.get("date"),
                "revenue": r.get("revenues") or r.get("revenue") or r.get("total_revenue"),
                "net_income": r.get("net_income_loss") or r.get("net_income"),
                "basic_eps": r.get("basic_earnings_per_share") or r.get("diluted_earnings_per_share") or r.get("eps"),
            }
        )
    df = pd.DataFrame(rows)
    df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce")
    df = df.dropna(subset=["period_end"]).sort_values("period_end")
    return df.reset_index(drop=True)


def fetch_leandata_income_annual(ticker: str) -> pd.DataFrame:
    try:
        import duckdb
    except ImportError:
        return pd.DataFrame()
    from lib_leandata import lean_root

    db = lean_root() / "data" / "depot.duckdb"
    if not db.exists():
        return pd.DataFrame()
    sym = ticker.upper()
    try:
        con = duckdb.connect(str(db), read_only=True)
        df = con.execute(
            f"SELECT * FROM statements_income_annual WHERE upper(ticker)='{sym}' OR upper(symbol)='{sym}' LIMIT 200"
        ).df()
        con.close()
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()
    # best-effort normalize
    lower = {c.lower(): c for c in df.columns}
    date_col = lower.get("period_end") or lower.get("report_date") or lower.get("fiscal_year") or lower.get("date")
    rev_col = lower.get("revenue") or lower.get("revenues") or lower.get("sales")
    eps_col = lower.get("eps") or lower.get("basic_eps") or lower.get("net_income")
    out = pd.DataFrame()
    if date_col:
        out["period_end"] = pd.to_datetime(df[date_col], errors="coerce")
    if rev_col:
        out["revenue"] = pd.to_numeric(df[rev_col], errors="coerce")
    if eps_col:
        out["basic_eps"] = pd.to_numeric(df[eps_col], errors="coerce")
    return out.dropna(subset=["period_end"]).sort_values("period_end").reset_index(drop=True)


def _yoy(series: pd.Series) -> pd.Series:
    return series.pct_change(1, fill_method=None) * 100.0


def consensus_asof(ratings: pd.DataFrame, asof: pd.Timestamp, lookback_days: int = 365) -> dict[str, Any]:
    if ratings is None or ratings.empty:
        return {"recom": None, "target": None, "n": 0, "bullish_pct": None}
    lo = asof - pd.Timedelta(days=lookback_days)
    window = ratings[(ratings["date"] <= asof) & (ratings["date"] >= lo)]
    if window.empty:
        window = ratings[ratings["date"] <= asof].tail(20)
    if window.empty:
        return {"recom": None, "target": None, "n": 0, "bullish_pct": None}
    latest = window.sort_values("date").groupby("firm", dropna=False).tail(1)
    recoms = latest["recom"].dropna()
    targets = latest["price_target"].dropna()
    bullish = latest["rating"].astype(str).str.lower().isin(
        {"strong buy", "strong_buy", "buy", "outperform", "overweight", "accumulate", "positive", "speculative buy"}
    )
    return {
        "recom": float(recoms.mean()) if len(recoms) else None,
        "target": float(targets.median()) if len(targets) else None,
        "n": int(len(latest)),
        "bullish_pct": float(bullish.mean() * 100) if len(latest) else None,
    }


def growth_asof(income: pd.DataFrame, asof: pd.Timestamp) -> dict[str, float | None]:
    if income is None or income.empty:
        return {"sales_yoy": None, "eps_yoy": None}
    hist = income[income["period_end"] <= asof].copy()
    if len(hist) < 2:
        return {"sales_yoy": None, "eps_yoy": None}
    hist = hist.sort_values("period_end")
    sales_yoy = None
    eps_yoy = None
    if "revenue" in hist.columns and hist["revenue"].notna().sum() >= 2:
        y = _yoy(hist["revenue"]).iloc[-1]
        sales_yoy = float(y) if pd.notna(y) else None
    if "basic_eps" in hist.columns and hist["basic_eps"].notna().sum() >= 2:
        y = _yoy(hist["basic_eps"]).iloc[-1]
        eps_yoy = float(y) if pd.notna(y) else None
    return {"sales_yoy": sales_yoy, "eps_yoy": eps_yoy}


def build_pit_eligibility_series(
    ticker: str,
    price_df: pd.DataFrame,
    toggles: dict,
    *,
    ratings: pd.DataFrame | None = None,
    income: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Daily eligible flag aligned to price_df dates."""
    tight = toggles.get("tight_buy", {}) or {}
    # Consensus averages dilute vs Finviz single recom — allow Buy band (<=2.0) in PIT
    max_recom = 2.0 if tight.get("enabled", True) else 2.5
    min_upside = float(tight.get("min_upside_pct", 15)) if tight.get("enabled", True) else 0.0
    min_bullish = 50.0  # % of latest firm ratings that are buy-ish

    if ratings is None:
        ratings = fetch_benzinga_ratings_massive(
            ticker,
            start=str(pd.Timestamp(price_df["Date"].iloc[0]).date()),
            end=str(pd.Timestamp(price_df["Date"].iloc[-1]).date()),
        )
    if income is None:
        income = fetch_massive_income_annual(ticker)
        if income.empty:
            income = fetch_leandata_income_annual(ticker)

    # Sample weekly to reduce cost, then ffill to daily
    dates = pd.to_datetime(price_df["Date"])
    sample_idx = list(range(0, len(price_df), 5)) + [len(price_df) - 1]
    sample_idx = sorted(set(sample_idx))
    sampled = []
    for i in sample_idx:
        r = price_df.iloc[i]
        asof = pd.Timestamp(r["Date"])
        px = float(r["Close"])
        cons = consensus_asof(ratings, asof)
        growth = growth_asof(income, asof)
        upside = None
        if cons["target"] and px > 0:
            upside = (float(cons["target"]) - px) / px * 100.0
        recom = cons["recom"]
        recom_ok = recom is not None and recom <= max_recom
        bullish_ok = cons["bullish_pct"] is None or cons["bullish_pct"] >= min_bullish
        upside_ok = upside is not None and upside >= min_upside
        eligible = bool((recom_ok or bullish_ok) and upside_ok)
        sampled.append(
            {
                "Date": asof,
                "eligible": eligible,
                "recom": recom,
                "upside_pct": None if upside is None else round(upside, 2),
                "target": cons["target"],
                "sales_yoy": None if growth["sales_yoy"] is None else round(growth["sales_yoy"], 2),
                "eps_yoy": None if growth["eps_yoy"] is None else round(growth["eps_yoy"], 2),
                "n_ratings": cons["n"],
                "bullish_pct": cons["bullish_pct"],
            }
        )
    pit = pd.DataFrame(sampled).set_index("Date").sort_index()
    # reindex to all price dates and forward-fill eligibility
    idx = pd.DatetimeIndex(pd.to_datetime(price_df["Date"]))
    full = pit.reindex(idx)
    full["eligible"] = full["eligible"].ffill().fillna(False)
    for col in ("recom", "upside_pct", "target", "sales_yoy", "eps_yoy", "n_ratings", "bullish_pct"):
        if col in full.columns:
            full[col] = full[col].ffill()
    full = full.reset_index().rename(columns={"index": "Date"})
    if full.columns[0] != "Date":
        full = full.rename(columns={full.columns[0]: "Date"})
    return full


def load_pit_bundle(ticker: str, start: str, end: str | None = None) -> dict[str, Any]:
    end = end or date.today().isoformat()
    ratings = fetch_benzinga_ratings_massive(ticker, start, end)
    income = fetch_massive_income_annual(ticker)
    if income.empty:
        income = fetch_leandata_income_annual(ticker)
    return {
        "ticker": ticker.upper(),
        "ratings_rows": int(len(ratings)),
        "income_rows": int(len(income)),
        "ratings": ratings,
        "income": income,
    }
