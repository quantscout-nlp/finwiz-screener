#!/usr/bin/env python3
"""Rebuild the AI/search index from data/tickers/*.json."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_finwiz import INDEX_PATH, rebuild_index  # noqa: E402


def main() -> int:
    index = rebuild_index()
    print(f"Indexed {index['count']} tickers -> {INDEX_PATH}")
    for d in index["docs"]:
        gate = "PASS" if d["passes_gate"] else "fail"
        print(
            f"  {d['ticker']:6} composite={d['scores']['composite']:5} "
            f"news={d['news_flow']:12} tech={d['technicals_label']:12} gate={gate}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
