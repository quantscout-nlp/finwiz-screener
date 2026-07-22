#!/usr/bin/env python3
"""Retro backtest Finwiz BUY/HOLD rules on yfinance history (core universe).

Examples:
  py -3 scripts/backtest.py
  py -3 scripts/backtest.py --start 2022-01-01 --sma-period 200
  py -3 scripts/backtest.py --fundamentals-mode technicals_only
  py -3 scripts/backtest.py --tickers NVDA,TSM,MU,CRDO,AVGO,ANET,LLY,PLTR
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_backtest import BacktestConfig, run_backtest, save_backtest  # noqa: E402
from lib_finwiz import load_toggles  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Finwiz retro backtest (yfinance + BUY/HOLD rules)")
    p.add_argument("--start", default="2023-01-01")
    p.add_argument("--end", default=None)
    p.add_argument("--tickers", default="", help="Comma-separated (default: all local tickers)")
    p.add_argument("--cash", type=float, default=100000)
    p.add_argument("--max-positions", type=int, default=5)
    p.add_argument("--max-position-pct", type=float, default=0.10)
    p.add_argument(
        "--fundamentals-mode",
        choices=["static", "technicals_only"],
        default="static",
        help="static=current Finviz eligibility + historical timing; technicals_only=ignore fundamentals",
    )
    p.add_argument("--sma-period", type=int, choices=[9, 20, 50, 100, 200], default=None)
    p.add_argument("--tag", default="core")
    args = p.parse_args()

    toggles = load_toggles()
    if args.sma_period is not None:
        toggles.setdefault("sma_filter", {})["period"] = args.sma_period
        toggles["sma_filter"]["enabled"] = True

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()] or None
    cfg = BacktestConfig(
        start=args.start,
        end=args.end,
        starting_cash=args.cash,
        max_open_positions=args.max_positions,
        max_position_pct=args.max_position_pct,
        fundamentals_mode=args.fundamentals_mode,
    )

    print("Running backtest… (downloading yfinance history)")
    result = run_backtest(tickers=tickers, cfg=cfg, toggles=toggles)
    path = save_backtest(result, tag=args.tag)
    print(json.dumps(result.summary, indent=2))
    print("\nNotes:")
    for n in result.notes:
        print(f"  - {n}")
    print(f"\nSaved: {path}")
    print(f"Equity: {path.parent / 'latest-equity.csv'}")
    return 0 if result.summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
