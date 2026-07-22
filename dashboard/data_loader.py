"""Load Finwiz screener data for the Streamlit dashboard."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib_finwiz import (  # noqa: E402
    ROOT as FINWIZ_ROOT,
    TICKERS_DIR,
    INDEX_PATH,
    TOGGLES_PATH,
    load_json,
    rebuild_index,
    save_toggles,
    load_toggles,
)

DEEP_DIVES = ROOT / "deep-dives"
SCREENERS = ROOT / "screeners"
PAPER_LEDGER = ROOT / "bot" / "ledger" / "paper_ledger.json"


def project_root() -> Path:
    return ROOT


def read_index(force_rebuild: bool = False) -> dict:
    if force_rebuild or not INDEX_PATH.exists():
        return rebuild_index()
    return load_json(INDEX_PATH)


def read_toggles() -> dict:
    return load_toggles()


def write_toggles(data: dict) -> None:
    from datetime import date

    data["updated"] = date.today().isoformat()
    save_toggles(data)


def docs_to_rows(index: dict) -> list[dict]:
    rows = []
    for d in index.get("docs", []):
        m = d.get("metrics") or {}
        t = d.get("technicals") or {}
        s = d.get("scores") or {}
        cap = d.get("capitulation") or {}
        rows.append(
            {
                "Ticker": d.get("ticker"),
                "Company": d.get("company"),
                "Action": d.get("action"),
                "Analyst": d.get("analyst_label"),
                "Recom": d.get("recom"),
                "Upside %": d.get("upside_pct"),
                "Composite": s.get("composite"),
                "Gate": "PASS" if d.get("passes_gate") else "FAIL",
                "News Flow": d.get("news_flow"),
                "Technicals": d.get("technicals_label"),
                "RSI": t.get("rsi14"),
                f"SMA{d.get('sma_period', 200)} %": d.get("sma_pct"),
                "YTD %": t.get("perf_ytd"),
                "DD 30d %": cap.get("drawdown_30d_pct"),
                "DD 90d %": cap.get("drawdown_90d_pct"),
                "Capitulation": "YES" if d.get("capitulation_pass") else "no",
                "Cap Score": cap.get("score"),
                "Price": m.get("price"),
                "Sales YoY %": m.get("sales_growth_yoy"),
                "EPS YoY %": m.get("eps_growth_yoy"),
                "PEG": m.get("peg"),
                "Fwd P/E": m.get("forward_pe"),
                "Target": m.get("target_price"),
                "Catalyst": (d.get("news") or {}).get("next_catalyst"),
                "Catalyst Date": (d.get("news") or {}).get("catalyst_date"),
                "Finviz": d.get("finviz_url"),
                "Reasons": "; ".join(d.get("action_reasons") or []),
                "_raw": d,
            }
        )
    return rows


def load_ticker_profile(ticker: str) -> dict | None:
    path = TICKERS_DIR / f"{ticker.upper()}.json"
    if path.exists():
        return load_json(path)
    return None


def load_deep_dive_md(ticker: str, index_doc: dict | None = None) -> str | None:
    rel = None
    if index_doc:
        rel = index_doc.get("deep_dive_path")
    if not rel:
        for p in DEEP_DIVES.glob(f"{ticker.upper()}*.md"):
            return p.read_text(encoding="utf-8")
        return None
    path = ROOT / rel
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def finviz_hits_url(tickers: list[str], view: str = "111") -> str:
    from urllib.parse import quote

    return f"https://finviz.com/screener.ashx?v={view}&t={quote(','.join(tickers), safe=',')}"


def read_url_file(name: str) -> str | None:
    path = SCREENERS / name
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return None


def read_paper_ledger() -> dict | None:
    if PAPER_LEDGER.exists():
        return load_json(PAPER_LEDGER)
    return None
