#!/usr/bin/env python3
"""Print BUY / HOLD / SELL / AVOID ranking table for all tickers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_finwiz import rebuild_index  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--action", choices=["BUY", "HOLD", "SELL", "AVOID"], default=None)
    p.add_argument("--gate-only", action="store_true")
    args = p.parse_args()

    index = rebuild_index()
    docs = index["docs"]
    if args.gate_only:
        docs = [d for d in docs if d.get("passes_gate")]
    if args.action:
        docs = [d for d in docs if d.get("action") == args.action]

    from lib_finwiz import load_toggles

    toggles = load_toggles()
    sma = toggles.get("sma_filter") or {}
    print(
        f"Toggles: screener={toggles.get('screener_enabled')} "
        f"SMA={sma.get('enabled')}/{sma.get('period')} "
        f"tight={toggles.get('tight_buy', {}).get('enabled')} "
        f"capitulation={toggles.get('capitulation_mode', {}).get('enabled')}"
    )
    print(f"{'TICK':6} {'ACTION':6} {'ANALYST':12} {'RECOM':5} {'UPSIDE':7} {'COMP':5} {'SMA%':7} {'GATE':4}  REASONS")
    print("-" * 110)
    for d in docs:
        print(
            f"{d['ticker']:6} {d.get('action', '?'):6} {str(d.get('analyst_label', '')):12} "
            f"{str(d.get('recom')):5} {str(d.get('upside_pct')):7} "
            f"{d.get('scores', {}).get('composite'):5} "
            f"{str(d.get('sma_pct')):7} "
            f"{'PASS' if d.get('passes_gate') else 'fail':4}  "
            f"{'; '.join((d.get('action_reasons') or [])[:2])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
