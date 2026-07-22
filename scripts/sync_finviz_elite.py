#!/usr/bin/env python3
"""Sync live Finviz Elite export data into data/tickers/*.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from finviz_elite import elite_configured, sync_tickers  # noqa: E402
from lib_finwiz import rebuild_index  # noqa: E402


def main() -> int:
    if not elite_configured():
        print("FINVIZ_API_KEY not set. Add your Elite API token to environment:")
        print("  $env:FINVIZ_API_KEY = \"your-token\"")
        print("Generate at: https://elite.finviz.com/api_explanation")
        return 1

    result = sync_tickers()
    print(json.dumps(result, indent=2))
    if not result.get("ok"):
        return 1

    index = rebuild_index()
    print(f"\nIndex rebuilt: {index.get('count')} tickers | {index.get('updated')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
