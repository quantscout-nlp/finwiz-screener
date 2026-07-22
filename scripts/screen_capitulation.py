#!/usr/bin/env python3
"""Mean-reversion / capitulation second screener.

Primary output = YOUR Finwiz hits as Finviz &t= ticker-list URLs.
Market-wide Finviz filters are labeled DISCOVERY only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_finwiz import (  # noqa: E402
    ROOT,
    load_json,
    load_toggles,
    rebuild_index,
)

CAP_CFG = ROOT / "config" / "capitulation.screener.json"
SCREENERS = ROOT / "screeners"


def finviz_hits_url(tickers: list[str], view: str = "111", filters: str = "") -> str:
    t = ",".join(tickers)
    url = f"https://finviz.com/screener.ashx?v={view}&t={quote(t, safe=',')}"
    if filters:
        url += f"&f={filters}"
    return url


def main() -> int:
    p = argparse.ArgumentParser(description="Capitulation / mean-reversion screener")
    p.add_argument("--json", action="store_true")
    p.add_argument("--min-score", type=int, default=50)
    args = p.parse_args()

    toggles = load_toggles()
    if not toggles.get("capitulation_mode", {}).get("enabled", True):
        print("capitulation_mode is OFF. Enable with:")
        print('  py -3 scripts\\toggle.py --capitulation on')
        return 1

    index = rebuild_index()
    hits = []
    for d in index["docs"]:
        cap = d.get("capitulation") or {}
        if not cap.get("passes"):
            continue
        if (cap.get("score") or 0) < args.min_score:
            continue
        hits.append(d)

    hits.sort(key=lambda d: (d.get("capitulation", {}).get("score") or 0), reverse=True)
    tickers = [d["ticker"] for d in hits]

    if args.json:
        print(json.dumps([{
            "ticker": d["ticker"],
            "action": d.get("action"),
            "capitulation": d.get("capitulation"),
            "recom": d.get("recom"),
            "finviz_url": d.get("finviz_url"),
        } for d in hits], indent=2))
        return 0

    print(f"Capitulation screener — {len(hits)} YOUR Finwiz hits | SMA toggle period={toggles.get('sma_filter', {}).get('period')}")
    print(f"{'TICK':6} {'SCORE':5} {'DD%':6} {'RSI':5} {'SMA%':7} {'ACTION':6}  REASONS")
    print("-" * 90)
    for d in hits:
        c = d["capitulation"]
        print(
            f"{d['ticker']:6} {c.get('score', 0):5} "
            f"{str(c.get('drawdown_worst_pct')):6} {str(c.get('rsi14')):5} "
            f"{str(c.get('sma_pct')):7} {d.get('action', '?'):6}  "
            f"{'; '.join(c.get('reasons') or [])}"
        )

    SCREENERS.mkdir(parents=True, exist_ok=True)
    print("\n=== Finviz URLs for YOUR screened hits (use these) ===")
    if tickers:
        # Overview of your capitulation hits only
        url_overview = finviz_hits_url(tickers, view="111")
        # Performance view of your hits
        url_perf = finviz_hits_url(tickers, view="141")
        # Technical view + below SMA50 within your list
        url_tech = finviz_hits_url(tickers, view="171", filters="ta_sma50_pb")
        mapping = {
            "YOUR_capitulation_hits_overview": url_overview,
            "YOUR_capitulation_hits_performance": url_perf,
            "YOUR_capitulation_hits_below_sma50": url_tech,
        }
        for name, url in mapping.items():
            print(f"  {name}:")
            print(f"    {url}")
            (SCREENERS / f"{name}.url.txt").write_text(url + "\n", encoding="utf-8")
        # Also overwrite the old misleading filenames to point at YOUR hits
        (SCREENERS / "capitulation-oversold_quality.url.txt").write_text(url_overview + "\n", encoding="utf-8")
        (SCREENERS / "capitulation-correction_30_90d.url.txt").write_text(url_perf + "\n", encoding="utf-8")
        (SCREENERS / "capitulation-deep_drawdown.url.txt").write_text(url_tech + "\n", encoding="utf-8")
        print(f"\n  Tickers locked in URL: {', '.join(tickers)}")
    else:
        print("  (no capitulation hits right now)")

    cfg = load_json(CAP_CFG)
    print("\n=== Market-wide DISCOVERY only (NOT your Finwiz picks) ===")
    for name, url in (cfg.get("finviz_urls_market_discovery") or cfg.get("finviz_urls") or {}).items():
        print(f"  discovery_{name}: {url}")
        (SCREENERS / f"market-discovery-{name}.url.txt").write_text(url + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
