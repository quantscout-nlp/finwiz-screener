"""Finviz Elite export API — live quote/metrics sync into local ticker JSON."""

from __future__ import annotations

import csv
import io
import os
import re
from datetime import date
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from lib_finwiz import TICKERS_DIR, load_all_tickers, load_json, save_json

ELITE_EXPORT = "https://elite.finviz.com/export/screener.ashx"
# Views: 141=performance, 152=valuation, 171=technical
DEFAULT_VIEWS = ("152", "141", "171")


def api_key() -> str | None:
    """Resolve Finviz Elite token from common env names (never log the value)."""
    for name in (
        "FINVIZ_API_KEY",
        "FINVIZ_ELITE_TOKEN",
        "FINWIZ_FINVIZ_API_KEY",
        "FINWIZ_API_KEY",  # common typo / alternate naming
    ):
        val = (os.environ.get(name) or "").strip()
        if val and not val.startswith("your-"):
            return val
    return None


def elite_configured() -> bool:
    return bool(api_key())


def _norm_header(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _parse_num(raw: str | None) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "")
    if not s or s in ("-", "—", "N/A"):
        return None
    if s.endswith("%"):
        s = s[:-1]
    try:
        return float(s)
    except ValueError:
        return None


def fetch_export_csv(tickers: list[str], view: str = "152", timeout: int = 30) -> list[dict[str, str]]:
    key = api_key()
    if not key:
        raise RuntimeError("FINVIZ_API_KEY not set in environment")
    if not tickers:
        return []

    t_param = quote(",".join(tickers), safe=",")
    url = f"{ELITE_EXPORT}?v={view}&t={t_param}&auth={key}"
    req = Request(url, headers={"User-Agent": "FinwizScreener/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"Finviz Elite HTTP {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Finviz Elite network error: {exc.reason}") from exc

    if not text.strip():
        return []
    if text.lstrip().startswith("<"):
        raise RuntimeError("Finviz Elite returned HTML (check API token / subscription)")

    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, str]] = []
    for row in reader:
        if not row:
            continue
        norm = {_norm_header(k): (v or "").strip() for k, v in row.items() if k}
        ticker = norm.get("ticker") or norm.get("symbol")
        if ticker:
            rows.append(norm)
    return rows


def _pick(row: dict[str, str], *keys: str) -> str | None:
    for k in keys:
        nk = _norm_header(k)
        if nk in row and row[nk]:
            return row[nk]
    for k in keys:
        nk = _norm_header(k)
        for rk, rv in row.items():
            if nk in rk and rv:
                return rv
    return None


def merge_finviz_rows(rows_by_view: dict[str, list[dict[str, str]]]) -> dict[str, dict[str, Any]]:
    """Merge multi-view Finviz export rows into per-ticker field updates."""
    merged: dict[str, dict[str, Any]] = {}

    def ensure(t: str) -> dict[str, Any]:
        return merged.setdefault(t.upper(), {"metrics": {}, "technicals": {}})

    for _view, rows in rows_by_view.items():
        for row in rows:
            ticker = (_pick(row, "ticker", "symbol") or "").upper()
            if not ticker:
                continue
            slot = ensure(ticker)
            m, tech = slot["metrics"], slot["technicals"]

            price = _parse_num(_pick(row, "price"))
            if price is not None:
                m["price"] = price

            for src, dst in (
                ("forward p/e", "forward_pe"),
                ("peg", "peg"),
                ("p/e", "pe"),
                ("market cap", "market_cap"),
                ("gross margin", "gross_margin"),
                ("oper. margin", "profit_margin"),
                ("profit margin", "profit_margin"),
                ("debt/eq", "debt_equity"),
                ("sales growthpast 5y", "sales_growth_yoy"),
                ("sales growthqoq", "sales_growth_yoy"),
                ("eps growthpast 5y", "eps_growth_yoy"),
                ("eps growthqoq", "eps_growth_yoy"),
                ("eps growththis year", "eps_growth_yoy"),
                ("target price", "target_price"),
            ):
                val = _parse_num(_pick(row, src))
                if val is not None:
                    m[dst] = val

            recom = _parse_num(_pick(row, "recom"))
            if recom is not None:
                m["recom"] = recom

            cap_raw = _pick(row, "market cap")
            if cap_raw and not cap_raw.replace(".", "").replace(",", "").isdigit():
                m["market_cap"] = cap_raw

            for src, dst in (
                ("rsi (14)", "rsi14"),
                ("perf year", "perf_ytd"),
                ("perf ytd", "perf_ytd"),
                ("perf quarter", "perf_quarter"),
                ("perf month", "perf_month"),
                ("perf week", "perf_week"),
                ("52w high", "from_52w_high_pct"),
                ("beta", "beta"),
            ):
                val = _parse_num(_pick(row, src))
                if val is not None:
                    tech[dst] = val

            for src, dst in (
                ("sma20", "sma20_pct"),
                ("sma50", "sma50_pct"),
                ("sma200", "sma200_pct"),
            ):
                val = _parse_num(_pick(row, src))
                if val is not None:
                    tech[dst] = val

    return merged


def apply_updates_to_ticker(ticker_data: dict, updates: dict[str, Any]) -> dict:
    out = dict(ticker_data)
    if updates.get("metrics"):
        metrics = dict(out.get("metrics") or {})
        metrics.update({k: v for k, v in updates["metrics"].items() if v is not None})
        out["metrics"] = metrics
    if updates.get("technicals"):
        technicals = dict(out.get("technicals") or {})
        technicals.update({k: v for k, v in updates["technicals"].items() if v is not None})
        out["technicals"] = technicals
    out["updated"] = date.today().isoformat()
    out["finviz_elite_sync"] = datetime_now_iso()
    return out


def datetime_now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def sync_tickers(tickers: list[str] | None = None, views: tuple[str, ...] = DEFAULT_VIEWS) -> dict:
    """Pull Finviz Elite export for tickers and write into data/tickers/*.json."""
    if not elite_configured():
        return {"ok": False, "reason": "FINVIZ_API_KEY not set", "updated": []}

    all_t = load_all_tickers()
    tickers = tickers or [t["ticker"] for t in all_t]
    tickers = [t.upper() for t in tickers if t]

    rows_by_view: dict[str, list[dict[str, str]]] = {}
    for view in views:
        rows_by_view[view] = fetch_export_csv(tickers, view=view)

    merged = merge_finviz_rows(rows_by_view)
    updated: list[str] = []
    by_ticker = {t["ticker"].upper(): t for t in all_t}

    for sym, patch in merged.items():
        base = by_ticker.get(sym)
        if not base:
            continue
        path = TICKERS_DIR / f"{sym}.json"
        current = load_json(path) if path.exists() else base
        save_json(path, apply_updates_to_ticker(current, patch))
        updated.append(sym)

    return {
        "ok": True,
        "updated": updated,
        "count": len(updated),
        "views": list(views),
        "synced_at": datetime_now_iso(),
    }


def sync_if_configured() -> dict | None:
    if not elite_configured():
        return None
    return sync_tickers()
