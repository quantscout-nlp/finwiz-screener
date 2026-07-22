#!/usr/bin/env python3
"""Auto-add candidate tickers from Finviz Elite export or a ticker list.

Examples:
  py -3 scripts/auto_add_tickers.py --tickers AMD,ARM,ASML --status candidate
  py -3 scripts/auto_add_tickers.py --from-elite --limit 5
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from finviz_elite import elite_configured, fetch_export_csv, merge_finviz_rows  # noqa: E402
from lib_finwiz import (  # noqa: E402
    ROOT,
    TICKERS_DIR,
    WATCHLISTS_DIR,
    load_json,
    load_weights,
    rebuild_index,
    save_json,
    score_ticker,
)


def upsert_candidate(
    ticker: str,
    *,
    company: str = "",
    status: str = "candidate",
    patch: dict | None = None,
) -> Path:
    ticker = ticker.upper().strip()
    path = TICKERS_DIR / f"{ticker}.json"
    if path.exists():
        data = load_json(path)
    else:
        data = load_json(ROOT / "templates" / "ticker.template.json")
        data["ticker"] = ticker
        data["finviz_url"] = f"https://finviz.com/quote.ashx?t={ticker}"
        data["deep_dive"]["included_reason"] = "Auto-added candidate — review before promoting to core."
        data["deep_dive"]["news_flow"] = "moderate"
        data["deep_dive"]["technicals"] = "workable"
        data["tags"] = ["growth", "candidate", "auto-added"]

    if company:
        data["company"] = company
    data["status"] = status
    if patch:
        if patch.get("metrics"):
            data.setdefault("metrics", {}).update(patch["metrics"])
        if patch.get("technicals"):
            data.setdefault("technicals", {}).update(patch["technicals"])
    data["updated"] = date.today().isoformat()
    data["deep_dive"]["scores"] = score_ticker(data, load_weights())
    save_json(path, data)
    return path


def update_candidates_watchlist(tickers: list[str]) -> None:
    path = WATCHLISTS_DIR / "candidates.json"
    wl = load_json(path) if path.exists() else {"name": "candidates", "tickers": []}
    existing = {t.upper() for t in wl.get("tickers") or []}
    for t in tickers:
        existing.add(t.upper())
    wl["tickers"] = sorted(existing)
    wl["updated"] = date.today().isoformat()
    wl["notes"] = "Auto-updated by scripts/auto_add_tickers.py"
    save_json(path, wl)


def main() -> int:
    p = argparse.ArgumentParser(description="Auto-add Finwiz candidate tickers")
    p.add_argument("--tickers", default="", help="Comma-separated tickers")
    p.add_argument("--from-elite", action="store_true", help="Pull top rows from Elite export of existing + optional filters")
    p.add_argument("--elite-tickers", default="", help="With --from-elite, tickers to fetch (default: none = skip)")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--status", default="candidate", choices=["candidate", "core", "watch"])
    p.add_argument("--rebuild", action="store_true", default=True)
    args = p.parse_args()

    added: list[str] = []
    manual = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    for t in manual[: args.limit]:
        upsert_candidate(t, status=args.status)
        added.append(t)

    if args.from_elite:
        if not elite_configured():
            print("FINVIZ_API_KEY not set — cannot --from-elite")
            return 1
        et = [t.strip().upper() for t in args.elite_tickers.split(",") if t.strip()] or manual
        if not et:
            print("Provide --elite-tickers or --tickers with --from-elite")
            return 1
        rows = {"152": fetch_export_csv(et, view="152"), "171": fetch_export_csv(et, view="171")}
        merged = merge_finviz_rows(rows)
        for sym, patch in list(merged.items())[: args.limit]:
            company = ""
            upsert_candidate(sym, company=company, status=args.status, patch=patch)
            if sym not in added:
                added.append(sym)

    if not added:
        print("No tickers added. Pass --tickers AMD,ARM or --from-elite --elite-tickers AMD,ARM")
        return 1

    update_candidates_watchlist(added)
    if args.rebuild:
        rebuild_index()
    print(f"Added/updated: {', '.join(added)}")
    print(f"Watchlist: {WATCHLISTS_DIR / 'candidates.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
