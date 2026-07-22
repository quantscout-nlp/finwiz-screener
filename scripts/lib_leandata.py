"""Read bars from local LeanData depot (F:/LeanData) without API keys.

Preferred: DuckDB views (read_only). Fallback: parquet partitions under MarketData/bars.
Resolutions: 1Min, 5Min, 15Min, 1Hour, Day.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import pandas as pd

Resolution = Literal["1Min", "5Min", "15Min", "1Hour", "Day"]

VIEW_MAP = {
    "1Min": "bars_1min",
    "5Min": "bars_5min",
    "15Min": "bars_15min",
    "1Hour": "bars_1hour",
    "Day": "bars_day",
}

PARQUET_TF = {
    "1Min": "1Min",
    "5Min": "5Min",
    "15Min": "15Min",
    "1Hour": "1Hour",
    "Day": "Day",
}


def lean_root() -> Path:
    return Path(os.environ.get("LEANDATA_ROOT", r"F:\LeanData"))


def lean_available() -> bool:
    root = lean_root()
    return (root / "data" / "depot.duckdb").exists() or (root / "MarketData" / "bars").exists()


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    # Common LeanData / DuckDB column variants
    colmap = {}
    lower = {c.lower(): c for c in out.columns}
    for cand in ("bar_date", "bar_timestamp", "date", "timestamp", "ts", "time", "datetime"):
        if cand in lower:
            colmap[lower[cand]] = "Date"
            break
    for cand in ("close", "c", "adj_close", "adjclose"):
        if cand in lower:
            colmap[lower[cand]] = "Close"
            break
    out = out.rename(columns=colmap)
    if "Date" not in out.columns or "Close" not in out.columns:
        return pd.DataFrame()
    out["Date"] = pd.to_datetime(out["Date"], utc=False, errors="coerce")
    if getattr(out["Date"].dt, "tz", None) is not None:
        out["Date"] = out["Date"].dt.tz_localize(None)
    out["Close"] = pd.to_numeric(out["Close"], errors="coerce")
    out = out.dropna(subset=["Date", "Close"]).sort_values("Date").drop_duplicates("Date")
    return out[["Date", "Close"]].reset_index(drop=True)


def fetch_leandata_duckdb(
    ticker: str,
    start: str,
    end: str | None = None,
    resolution: Resolution = "Day",
) -> pd.DataFrame:
    try:
        import duckdb
    except ImportError:
        return pd.DataFrame()
    db = lean_root() / "data" / "depot.duckdb"
    if not db.exists():
        return pd.DataFrame()
    view = VIEW_MAP.get(resolution, "bars_day")
    sym = ticker.upper()
    if resolution == "Day":
        q = (
            f"SELECT symbol, bar_date, open, high, low, close, volume FROM {view} "
            f"WHERE symbol='{sym}' AND bar_date >= '{start}'"
            + (f" AND bar_date <= '{end}'" if end else "")
            + " ORDER BY bar_date"
        )
        queries = [q]
    else:
        queries = [
            f"SELECT * FROM {view} WHERE symbol='{sym}' AND bar_timestamp >= '{start}'"
            + (f" AND bar_timestamp <= '{end} 23:59:59'" if end else "")
            + " ORDER BY bar_timestamp",
            f"SELECT * FROM {view} WHERE symbol='{sym}' AND date >= '{start}'"
            + (f" AND date <= '{end}'" if end else "")
            + " ORDER BY bar_timestamp",
        ]
    try:
        con = duckdb.connect(str(db), read_only=True)
    except Exception:
        return pd.DataFrame()
    try:
        for q in queries:
            try:
                df = con.execute(q).df()
                norm = _normalize(df)
                if not norm.empty:
                    if start:
                        norm = norm[norm["Date"] >= pd.Timestamp(start)]
                    if end:
                        norm = norm[norm["Date"] <= pd.Timestamp(end)]
                    return norm.reset_index(drop=True)
            except Exception:
                continue
    finally:
        con.close()
    return pd.DataFrame()


def fetch_leandata_parquet(
    ticker: str,
    start: str,
    end: str | None = None,
    resolution: Resolution = "Day",
) -> pd.DataFrame:
    root = lean_root() / "MarketData" / "bars"
    tf = PARQUET_TF.get(resolution, "Day")
    sym = ticker.upper()
    frames: list[pd.DataFrame] = []

    if resolution == "1Min":
        # MarketData\bars\1Min\date=YYYY-MM-DD\data.parquet  (all symbols)
        base = root / "1Min"
        if not base.exists():
            return pd.DataFrame()
        for part in sorted(base.glob("date=*")):
            day = part.name.split("=", 1)[-1]
            if start and day < start[:10]:
                continue
            if end and day > end[:10]:
                continue
            fp = part / "data.parquet"
            if not fp.exists():
                continue
            try:
                df = pd.read_parquet(fp)
            except Exception:
                continue
            # filter symbol
            scol = None
            for c in df.columns:
                if c.lower() in ("symbol", "ticker", "sym"):
                    scol = c
                    break
            if scol:
                df = df[df[scol].astype(str).str.upper() == sym]
            frames.append(df)
    else:
        # MarketData\bars\{tf}\symbol=X\... or symbol=X\year=Y\data.parquet
        base = root / tf / f"symbol={sym}"
        if not base.exists():
            # try lowercase
            base = root / tf / f"symbol={sym.lower()}"
        if base.exists():
            files = list(base.rglob("data.parquet"))
            for fp in files:
                try:
                    frames.append(pd.read_parquet(fp))
                except Exception:
                    continue
        # Day may be single file
        single = root / tf / f"symbol={sym}" / "data.parquet"
        if single.exists():
            try:
                frames.append(pd.read_parquet(single))
            except Exception:
                pass

    if not frames:
        # CSV legacy fallback
        csv = lean_root() / "data" / f"{sym}_historical.csv"
        if csv.exists() and resolution == "Day":
            try:
                df = pd.read_csv(csv)
                return _normalize(df)
            except Exception:
                return pd.DataFrame()
        return pd.DataFrame()

    raw = pd.concat(frames, ignore_index=True)
    norm = _normalize(raw)
    if start:
        norm = norm[norm["Date"] >= pd.Timestamp(start)]
    if end:
        norm = norm[norm["Date"] <= pd.Timestamp(end)]
    return norm.reset_index(drop=True)


def fetch_leandata_bars(
    ticker: str,
    start: str,
    end: str | None = None,
    resolution: Resolution = "Day",
) -> tuple[pd.DataFrame, str]:
    """Return (df, source_tag)."""
    if not lean_available():
        return pd.DataFrame(), "leandata_missing"
    df = fetch_leandata_duckdb(ticker, start, end, resolution)
    if df is not None and not df.empty:
        return df, f"leandata_duckdb_{resolution}"
    df = fetch_leandata_parquet(ticker, start, end, resolution)
    if df is not None and not df.empty:
        return df, f"leandata_parquet_{resolution}"
    return pd.DataFrame(), "leandata_empty"
