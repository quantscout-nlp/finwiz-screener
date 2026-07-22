#!/usr/bin/env python3
"""Build Finviz URLs from YOUR Finwiz screened tickers (not the whole market).

Finviz can show a ticker list with &t=NVDA,TSM,...
Those are YOUR Finwiz hits. Market-wide &f= filters alone are discovery only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_finwiz import ROOT, rebuild_index, load_toggles  # noqa: E402

SCREENERS = ROOT / "screeners"


def finviz_list(tickers: list[str], view: str = "111", extra_filters: str = "") -> str:
    """Build a Finviz screener URL locked to an explicit ticker list."""
    t = ",".join(tickers)
    # v=111 overview, v=121 valuation, v=141 performance, v=171 technical
    base = f"https://finviz.com/screener.ashx?v={view}&t={quote(t, safe=',')}"
    if extra_filters:
        # Keep ticker list primary; optional filters narrow WITHIN the list
        base += f"&f={extra_filters}"
    return base


def write_url(name: str, url: str) -> Path:
    SCREENERS.mkdir(parents=True, exist_ok=True)
    path = SCREENERS / f"{name}.url.txt"
    path.write_text(url + "\n", encoding="utf-8")
    return path


def main() -> int:
    p = argparse.ArgumentParser(description="Export Finviz URLs for Finwiz screened hits")
    p.add_argument(
        "--set",
        choices=["buy", "hold", "gate", "capitulation", "all"],
        default="all",
        help="Which Finwiz result set to export",
    )
    args = p.parse_args()

    index = rebuild_index()
    docs = index["docs"]
    toggles = load_toggles()
    sma_period = toggles.get("sma_filter", {}).get("period", 200)

    buy = [d["ticker"] for d in docs if d.get("action") == "BUY"]
    hold = [d["ticker"] for d in docs if d.get("action") == "HOLD"]
    gate = [d["ticker"] for d in docs if d.get("passes_gate")]
    cap = [d["ticker"] for d in docs if d.get("capitulation_pass")]

    # Map SMA period to Finviz filter token (price above SMA)
    sma_above = {
        20: "ta_sma20_pa",
        50: "ta_sma50_pa",
        200: "ta_sma200_pa",
    }.get(int(sma_period), "ta_sma200_pa")
    # Analyst Strong Buy / Buy band approx: Buy or better
    analyst_buy = "an_recom_buybetter"  # Finviz: Buy or better

    sets = {
        "buy": ("YOUR Finwiz BUY hits (tight + SMA)", buy, "111", f"cap_largeover,{sma_above},{analyst_buy}"),
        "hold": ("YOUR Finwiz HOLD hits", hold, "111", ""),
        "gate": ("YOUR Finwiz gate-PASS universe", gate, "111", ""),
        "capitulation": (
            "YOUR Finwiz capitulation hits",
            cap,
            "141",
            "cap_largeover,ta_sma50_pb",  # within YOUR list: below SMA50 flavor
        ),
    }

    print("IMPORTANT: These URLs open Finviz with YOUR screened tickers (&t=...).")
    print("They are NOT the market-wide discovery screens (387/900+ names).\n")

    to_export = sets.keys() if args.set == "all" else [args.set]
    for key in to_export:
        label, tickers, view, filt = sets[key]
        if not tickers:
            print(f"{key}: (no tickers — nothing to open)")
            continue
        url = finviz_list(tickers, view=view, extra_filters=filt)
        path = write_url(f"finwiz-{key}-hits", url)
        print(f"{key.upper()} — {label}")
        print(f"  tickers: {', '.join(tickers)}")
        print(f"  url:     {url}")
        print(f"  saved:   {path}\n")

    # Also keep market discovery links clearly labeled separately
    discovery = {
        "market-discovery-oversold_quality": "https://finviz.com/screener.ashx?v=111&f=cap_largeover,ta_rsi_oversold30,ta_perf4w_u5,ta_sma50_pb&o=ticker",
        "market-discovery-correction_30_90d": "https://finviz.com/screener.ashx?v=141&f=cap_largeover,ta_perf4w_u10,ta_perf13w_u10&o=perf4w",
        "market-discovery-deep_drawdown": "https://finviz.com/screener.ashx?v=111&f=cap_largeover,ta_perf13w_u20,ta_rsi_os40&o=perf13w",
    }
    print("Market-wide DISCOVERY only (not your Finwiz picks):")
    for name, url in discovery.items():
        write_url(name, url)
        print(f"  {name}: {url}")

    # Convenience: openable compare of current BUY + capitulation
    if buy:
        write_url("finwiz-buy-hits", finviz_list(buy))
    if cap:
        write_url("finwiz-capitulation-hits", finviz_list(cap, view="141"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
