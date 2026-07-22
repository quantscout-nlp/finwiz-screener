"""Multi-provider market data for Finwiz backtests.

Providers (auto-fallback): Massive (Polygon-compatible) → Alpaca → Tiingo → yfinance.

Env vars (User-level Windows — already configured on this machine):
  MASSIVE_API_KEY / POLYGON_API_KEY, MASSIVE_REST_BASE_URL / MASSIVE_BASE_URL
  ALPACA_API_KEY + ALPACA_API_SECRET (or PAPER keys), ALPACA_DATA_BASE_URL, ALPACA_DATA_FEED
  TIINGO_API_KEY
  BENZINGA_API_KEY (news / ratings enrichment — optional)
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = (os.environ.get(n) or "").strip()
        if v and not v.lower().startswith("your-"):
            return v
    return default


def provider_status() -> dict[str, bool]:
    try:
        from lib_leandata import lean_available
        lean_ok = lean_available()
    except Exception:
        lean_ok = False
    return {
        "leandata": lean_ok,
        "massive": bool(_env("MASSIVE_API_KEY", "POLYGON_API_KEY")),
        "alpaca": bool(
            _env("ALPACA_API_KEY", "ALPACA_API_PAPER_KEY", "ALPACA_PAPER1_KEY_ID")
            and _env("ALPACA_API_SECRET", "ALPACA_API_PAPER_SECRET", "ALPACA_PAPER1_SECRET_KEY")
        ),
        "tiingo": bool(_env("TIINGO_API_KEY")),
        "benzinga": bool(_env("BENZINGA_API_KEY") or _env("MASSIVE_API_KEY", "POLYGON_API_KEY")),
        "yfinance": True,
    }


def _http_json(url: str, headers: dict[str, str] | None = None, timeout: int = 60) -> Any:
    req = Request(url, headers=headers or {"User-Agent": "FinwizScreener/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["Date"] = pd.to_datetime(out["Date"]).dt.tz_localize(None)
    out["Close"] = out["Close"].astype(float)
    out = out.dropna(subset=["Close"]).sort_values("Date").drop_duplicates("Date").reset_index(drop=True)
    return out[["Date", "Close"]]


# ---- Massive / Polygon-compatible aggregates ----

def fetch_massive_daily(ticker: str, start: str, end: str | None = None) -> pd.DataFrame:
    key = _env("MASSIVE_API_KEY", "POLYGON_API_KEY")
    if not key:
        return pd.DataFrame()
    base = _env("MASSIVE_REST_BASE_URL", "MASSIVE_BASE_URL", "POLYGON_BASE_URL", default="https://api.massive.com").rstrip("/")
    end = end or date.today().isoformat()
    # Paginate via next_url
    url = f"{base}/v2/aggs/ticker/{ticker.upper()}/range/1/day/{start}/{end}?adjusted=true&sort=asc&limit=50000&apiKey={key}"
    rows: list[dict] = []
    for _ in range(20):
        try:
            payload = _http_json(url)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            break
        for r in payload.get("results") or []:
            ts = r.get("t")
            if ts is None:
                continue
            rows.append({"Date": datetime.utcfromtimestamp(ts / 1000.0), "Close": r.get("c")})
        nxt = payload.get("next_url")
        if not nxt:
            break
        # next_url may already include query; ensure apiKey
        url = nxt if "apiKey=" in nxt else (nxt + ("&" if "?" in nxt else "?") + f"apiKey={key}")
    if not rows:
        return pd.DataFrame()
    return _normalize_ohlc(pd.DataFrame(rows))


def fetch_massive_ratios(ticker: str) -> dict[str, Any] | None:
    """Latest ratios snapshot (point-in-time daily). Best-effort."""
    key = _env("MASSIVE_API_KEY", "POLYGON_API_KEY")
    if not key:
        return None
    base = _env("MASSIVE_REST_BASE_URL", "MASSIVE_BASE_URL", default="https://api.massive.com").rstrip("/")
    url = f"{base}/stocks/financials/v1/ratios?ticker={ticker.upper()}&limit=1&apiKey={key}"
    try:
        payload = _http_json(url)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None
    results = payload.get("results") or payload.get("data") or []
    if isinstance(results, list) and results:
        return results[0] if isinstance(results[0], dict) else None
    if isinstance(payload, dict) and "price" in payload:
        return payload
    return None


# ---- Alpaca bars (IEX / SIP feed) ----

def fetch_alpaca_daily(ticker: str, start: str, end: str | None = None) -> pd.DataFrame:
    key = _env("ALPACA_API_KEY", "ALPACA_API_PAPER_KEY", "ALPACA_PAPER1_KEY_ID")
    secret = _env("ALPACA_API_SECRET", "ALPACA_API_PAPER_SECRET", "ALPACA_PAPER1_SECRET_KEY")
    if not key or not secret:
        return pd.DataFrame()
    base = _env("ALPACA_DATA_BASE_URL", default="https://data.alpaca.markets").rstrip("/")
    feed = _env("ALPACA_DATA_FEED", "ALPACA_FEED", default="iex")
    end = end or date.today().isoformat()
    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "User-Agent": "FinwizScreener/1.0",
    }
    rows: list[dict] = []
    page_token = None
    for _ in range(30):
        q = {
            "timeframe": "1Day",
            "start": start,
            "end": end,
            "adjustment": "all",
            "feed": feed,
            "limit": 10000,
        }
        if page_token:
            q["page_token"] = page_token
        url = f"{base}/v2/stocks/{ticker.upper()}/bars?{urlencode(q)}"
        try:
            payload = _http_json(url, headers=headers)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            break
        for b in payload.get("bars") or []:
            rows.append({"Date": b.get("t"), "Close": b.get("c")})
        page_token = payload.get("next_page_token")
        if not page_token:
            break
    if not rows:
        return pd.DataFrame()
    return _normalize_ohlc(pd.DataFrame(rows))


# ---- Tiingo ----

def fetch_tiingo_daily(ticker: str, start: str, end: str | None = None) -> pd.DataFrame:
    key = _env("TIINGO_API_KEY")
    if not key:
        return pd.DataFrame()
    end = end or date.today().isoformat()
    q = urlencode({"startDate": start, "endDate": end, "format": "json", "token": key})
    url = f"https://api.tiingo.com/tiingo/daily/{ticker.lower()}/prices?{q}"
    try:
        payload = _http_json(url, headers={"Content-Type": "application/json", "User-Agent": "FinwizScreener/1.0"})
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return pd.DataFrame()
    if not isinstance(payload, list) or not payload:
        return pd.DataFrame()
    rows = []
    for r in payload:
        rows.append({"Date": r.get("date") or r.get("Date"), "Close": r.get("adjClose") or r.get("close")})
    return _normalize_ohlc(pd.DataFrame(rows))


# ---- yfinance fallback ----

def fetch_yfinance_daily(ticker: str, start: str, end: str | None = None) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError:
        return pd.DataFrame()
    raw = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True, threads=False)
    if raw is None or raw.empty:
        return pd.DataFrame()
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]) for c in df.columns]
    df = df.reset_index()
    date_col = "Date" if "Date" in df.columns else df.columns[0]
    close = df["Close"] if "Close" in df.columns else None
    if close is None:
        return pd.DataFrame()
    return _normalize_ohlc(pd.DataFrame({"Date": df[date_col], "Close": close}))


# ---- Benzinga news count (enrichment only) ----

def fetch_benzinga_news_count(ticker: str, start: str, end: str | None = None) -> int | None:
    key = _env("BENZINGA_API_KEY")
    if not key:
        return None
    endpoint = _env("BENZINGA_NEWS_ENDPOINT", default="https://api.benzinga.com/api/v2/news")
    end = end or date.today().isoformat()
    q = urlencode({"token": key, "tickers": ticker.upper(), "displayOutput": "headline", "pageSize": 100, "dateFrom": start, "dateTo": end})
    url = f"{endpoint}?{q}"
    try:
        payload = _http_json(url)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        items = payload.get("data") or payload.get("news") or payload.get("results") or []
        return len(items) if isinstance(items, list) else None
    return None


def fetch_daily_bars(
    ticker: str,
    start: str,
    end: str | None = None,
    provider: str = "auto",
    resolution: str = "Day",
) -> tuple[pd.DataFrame, str]:
    """Return (ohlc_df, provider_used). resolution used for LeanData (Day/1Min/5Min/15Min/1Hour)."""
    if provider in ("lean", "leandata") or (provider == "auto" and resolution != "Day"):
        try:
            from lib_leandata import fetch_leandata_bars

            df, tag = fetch_leandata_bars(ticker, start, end, resolution=resolution if resolution in ("1Min", "5Min", "15Min", "1Hour", "Day") else "Day")
            if df is not None and not df.empty:
                return df, tag
        except Exception:
            pass
        if provider in ("lean", "leandata"):
            return pd.DataFrame(), "leandata_empty"

    order = {
        "auto": ["leandata", "massive", "alpaca", "tiingo", "yfinance"],
        "massive": ["massive", "yfinance"],
        "alpaca": ["alpaca", "yfinance"],
        "tiingo": ["tiingo", "yfinance"],
        "yfinance": ["yfinance"],
        "lean": ["leandata"],
        "leandata": ["leandata"],
    }.get(provider, ["leandata", "massive", "alpaca", "tiingo", "yfinance"])

    def _lean():
        from lib_leandata import fetch_leandata_bars

        return fetch_leandata_bars(ticker, start, end, resolution="Day")

    fetchers = {
        "leandata": lambda t, s, e: _lean()[0],
        "massive": fetch_massive_daily,
        "alpaca": fetch_alpaca_daily,
        "tiingo": fetch_tiingo_daily,
        "yfinance": fetch_yfinance_daily,
    }
    for name in order:
        try:
            if name == "leandata":
                df, tag = _lean()
                used = tag
            else:
                df = fetchers[name](ticker, start, end)
                used = name
        except Exception:
            df = pd.DataFrame()
            used = name
        if df is not None and not df.empty and len(df) >= 50:
            return df, used
    return pd.DataFrame(), "none"


def years_ago_iso(years: float) -> str:
    return (date.today() - timedelta(days=int(years * 365.25))).isoformat()
