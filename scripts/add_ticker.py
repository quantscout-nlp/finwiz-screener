#!/usr/bin/env python3
"""Add or update a ticker profile (expandable registry).

Example:
  py -3 scripts/add_ticker.py ANET --news strong --technicals workable --status candidate
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_finwiz import TICKERS_DIR, load_json, load_weights, rebuild_index, save_json, score_ticker  # noqa: E402

TEMPLATE = TICKERS_DIR.parent.parent / "templates" / "ticker.template.json"


def main() -> int:
    p = argparse.ArgumentParser(description="Add expandable Finwiz ticker")
    p.add_argument("ticker", help="Ticker symbol")
    p.add_argument("--company", default="")
    p.add_argument("--news", choices=["weak", "moderate", "strong", "exceptional"], default="moderate")
    p.add_argument(
        "--technicals",
        choices=["broken", "fragile", "workable", "constructive", "strong"],
        default="workable",
    )
    p.add_argument("--status", choices=["candidate", "core", "watch", "archived"], default="candidate")
    p.add_argument("--reason", default="Added via add_ticker.py; fill metrics/news next.")
    p.add_argument("--tags", default="growth", help="Comma-separated tags")
    args = p.parse_args()

    ticker = args.ticker.upper().strip()
    path = TICKERS_DIR / f"{ticker}.json"
    if path.exists():
        data = load_json(path)
    else:
        data = load_json(TEMPLATE)
        data["ticker"] = ticker
        data["finviz_url"] = f"https://finviz.com/quote.ashx?t={ticker}"

    if args.company:
        data["company"] = args.company
    data["status"] = args.status
    data["deep_dive"]["news_flow"] = args.news
    data["deep_dive"]["technicals"] = args.technicals
    data["deep_dive"]["included_reason"] = args.reason
    data["tags"] = [t.strip() for t in args.tags.split(",") if t.strip()]
    data["updated"] = date.today().isoformat()

    scores = score_ticker(data, load_weights())
    data["deep_dive"]["scores"] = scores

    save_json(path, data)
    rebuild_index()
    print(f"Saved {path}")
    print(f"Scores: {scores}")
    print(f"Open Finviz: {data['finviz_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
