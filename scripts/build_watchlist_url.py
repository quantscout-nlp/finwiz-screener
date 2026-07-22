#!/usr/bin/env python3
"""Build a Finviz URL from a watchlist or Finwiz action set."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_finwiz import ROOT, WATCHLISTS_DIR, load_json, rebuild_index  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--watchlist", default="core-eight.json")
    p.add_argument("--gate-only", action="store_true")
    p.add_argument("--action", choices=["BUY", "HOLD", "SELL", "AVOID"])
    p.add_argument("--capitulation", action="store_true")
    args = p.parse_args()

    index = rebuild_index()
    docs = index["docs"]

    if args.capitulation:
        tickers = [d["ticker"] for d in docs if d.get("capitulation_pass")]
        label = "capitulation"
    elif args.action:
        tickers = [d["ticker"] for d in docs if d.get("action") == args.action]
        label = args.action.lower()
    elif args.gate_only:
        tickers = [d["ticker"] for d in docs if d["passes_gate"]]
        label = "gate"
    else:
        wl = load_json(WATCHLISTS_DIR / args.watchlist)
        tickers = wl.get("tickers", [])
        label = "watchlist"

    if not tickers:
        print("No tickers for this selection.")
        return 1

    url = "https://finviz.com/screener.ashx?v=111&t=" + quote(",".join(tickers), safe=",")
    out = ROOT / "screeners" / f"finwiz-{label}-hits.url.txt"
    out.write_text(url + "\n", encoding="utf-8")
    print(f"YOUR Finwiz {label} tickers: {', '.join(tickers)}")
    print(url)
    print(f"Wrote {out}")
    print("(This uses &t= so Finviz shows ONLY these names — not the whole market.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
