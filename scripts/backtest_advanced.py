#!/usr/bin/env python3
"""Advanced Finwiz backtest: 5–10y multi-provider prices + IS/OOS + Monte Carlo.

Uses Windows env keys when present:
  MASSIVE_API_KEY, ALPACA_API_KEY/SECRET, TIINGO_API_KEY, BENZINGA_API_KEY

Examples:
  py -3 scripts/backtest_advanced.py --years 10
  py -3 scripts/backtest_advanced.py --years 5 --provider massive --mc-sims 2000
  py -3 scripts/backtest_advanced.py --years 10 --fundamentals-mode technicals_only --oos-ratio 0.3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib_backtest_mc import AdvancedBacktestConfig, run_advanced_backtest  # noqa: E402
from lib_market_data import provider_status  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Finwiz advanced backtest (MC + IS/OOS)")
    p.add_argument("--years", type=float, default=10.0, help="Lookback years (5–10 recommended)")
    p.add_argument("--oos-ratio", type=float, default=0.30, help="Fraction reserved for out-of-sample")
    p.add_argument("--mc-sims", type=int, default=1000)
    p.add_argument("--mc-seed", type=int, default=42)
    p.add_argument("--provider", choices=["auto", "lean", "leandata", "massive", "alpaca", "tiingo", "yfinance"], default="auto")
    p.add_argument("--fundamentals-mode", choices=["pit", "static", "technicals_only"], default="pit")
    p.add_argument("--resolution", choices=["Day", "1Hour", "15Min", "5Min", "1Min"], default="Day")
    p.add_argument("--sma-period", type=int, choices=[9, 20, 50, 100, 200], default=200)
    p.add_argument("--tickers", default="", help="Comma-separated (default: all local)")
    p.add_argument("--cash", type=float, default=100000)
    p.add_argument("--max-positions", type=int, default=5)
    args = p.parse_args()

    print("Provider status:", json.dumps(provider_status()))
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()] or None
    cfg = AdvancedBacktestConfig(
        years=args.years,
        oos_ratio=args.oos_ratio,
        mc_sims=args.mc_sims,
        mc_seed=args.mc_seed,
        price_provider=args.provider,
        fundamentals_mode=args.fundamentals_mode,
        starting_cash=args.cash,
        max_open_positions=args.max_positions,
        sma_period=args.sma_period,
        bar_resolution=args.resolution,
    )
    print(f"Running {args.years}y backtest via provider={args.provider} …")
    report = run_advanced_backtest(tickers=tickers, cfg=cfg)

    base = report.get("base_summary") or {}
    is_oos = report.get("is_oos") or {}
    mc = report.get("monte_carlo") or {}

    print("\n=== BASE ===")
    print(json.dumps({k: base.get(k) for k in (
        "ok", "start", "end", "total_return_pct", "cagr_pct", "max_drawdown_pct",
        "sharpe_approx", "trades", "win_rate_pct", "tickers_traded", "tickers_skipped",
    )}, indent=2))

    print("\n=== IN-SAMPLE / OUT-OF-SAMPLE ===")
    print(json.dumps({
        "is": is_oos.get("in_sample"),
        "oos": is_oos.get("out_of_sample"),
        "split": {"is_end": is_oos.get("is_end_date"), "oos_start": is_oos.get("oos_start_date")},
    }, indent=2))

    print("\n=== MONTE CARLO ===")
    print(json.dumps(mc, indent=2))
    print(f"\nSaved: data/backtests/advanced-latest.json")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
