#!/usr/bin/env python3
"""Run one paper-trading cycle from Finwiz action signals.

Live trading is intentionally NOT implemented here.
Set FINWIZ_LIVE_TRADING=1 only after a real broker adapter exists.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "scripts"))

from broker_paper import apply_signals, load_ledger  # noqa: E402
from lib_finwiz import load_json  # noqa: E402
from signals import build_signals  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Finwiz paper trading cycle")
    p.add_argument("--dry-run", action="store_true", help="Print intents without writing ledger")
    args = p.parse_args()

    cfg = load_json(ROOT / "bot" / "config.json")
    if os.environ.get("FINWIZ_LIVE_TRADING") == "1" or cfg.get("live", {}).get("enabled"):
        print("LIVE TRADING BLOCKED: no live broker adapter in this scaffold.")
        print("Use paper mode only. Unset FINWIZ_LIVE_TRADING.")
        return 2

    signals = build_signals(cfg)
    print(f"Signals: {len(signals)}")
    for s in signals:
        print(
            f"  {s['ticker']:6} {s['intent']:11} {s['action']:5} "
            f"analyst={s['analyst_label']} recom={s['recom']} upside={s['upside_pct']}%"
        )

    ledger = load_ledger(cfg.get("starting_cash", 100000))
    result = apply_signals(ledger, signals, cfg, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    if args.dry_run:
        print("(dry-run — ledger not written)")
    else:
        print(f"Ledger: {ROOT / 'bot' / 'ledger' / 'paper_ledger.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
