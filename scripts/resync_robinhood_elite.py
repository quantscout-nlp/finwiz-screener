#!/usr/bin/env python3
"""Re-sync Robinhood watchlist via fixed Elite column mapping."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from finviz_elite import sync_tickers  # noqa: E402
from lib_finwiz import rebuild_index  # noqa: E402


def main() -> int:
    wl = json.loads((ROOT / "watchlists" / "robinhood-retail.json").read_text(encoding="utf-8"))
    tickers = [t.upper() for t in (wl.get("tickers") or [])]
    print(f"syncing {len(tickers)} tickers in chunks of 20", flush=True)
    total = 0
    errors: list[str] = []
    for i in range(0, len(tickers), 20):
        batch = tickers[i : i + 20]
        try:
            result = sync_tickers(batch)
            n = int(result.get("count") or 0)
            total += n
            print(
                f"chunk {i // 20 + 1}: {batch[0]}..{batch[-1]} patched={n} ok={result.get('ok')}",
                flush=True,
            )
            if not result.get("ok"):
                errors.append(str(result))
        except Exception as exc:
            print(f"chunk fail: {exc}", flush=True)
            errors.append(str(exc))
            time.sleep(10)
        time.sleep(3)
    idx = rebuild_index()
    amzn = next(d for d in idx["docs"] if d["ticker"] == "AMZN")
    print(
        f"done patched={total} index={len(idx['docs'])} errors={len(errors)} "
        f"AMZN company={amzn.get('company')} peg={(amzn.get('metrics') or {}).get('peg')} "
        f"rsi={(amzn.get('technicals') or {}).get('rsi14')}",
        flush=True,
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
