#!/usr/bin/env python3
"""One automation cycle: Elite sync → rebuild → optional deep-dives → paper trades.

Designed for Windows Task Scheduler (always-on background).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "bot"))

from auto_deep_dive import generate_for_ticker  # noqa: E402
from broker_paper import apply_signals, load_ledger  # noqa: E402
from finviz_elite import elite_configured, sync_if_configured  # noqa: E402
from lib_finwiz import load_json, rebuild_index  # noqa: E402
from signals import build_signals  # noqa: E402

LOG_DIR = ROOT / "data" / "automation_logs"


def log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().isoformat(timespec='seconds')} | {msg}"
    print(line)
    with (LOG_DIR / "automation.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    p = argparse.ArgumentParser(description="Finwiz automation cycle")
    p.add_argument("--skip-elite", action="store_true")
    p.add_argument("--skip-paper", action="store_true")
    p.add_argument("--paper-dry-run", action="store_true")
    p.add_argument("--deep-dives", action="store_true", help="Auto-generate missing deep-dive stubs")
    p.add_argument("--deep-dive-llm", action="store_true")
    args = p.parse_args()

    summary: dict = {"ok": True, "steps": []}

    if not args.skip_elite:
        if elite_configured():
            try:
                result = sync_if_configured()
                summary["steps"].append({"elite_sync": result})
                log(f"Elite sync: {result}")
            except Exception as exc:
                summary["ok"] = False
                summary["steps"].append({"elite_sync_error": str(exc)})
                log(f"Elite sync FAILED: {exc}")
        else:
            log("Elite sync skipped — FINVIZ_API_KEY not set")
            summary["steps"].append({"elite_sync": "skipped_no_key"})

    index = rebuild_index()
    summary["steps"].append({"rebuild": {"count": index.get("count"), "updated": index.get("updated")}})
    log(f"Index rebuilt: {index.get('count')} names")

    if args.deep_dives:
        tickers = [d["ticker"] for d in index.get("docs", [])]
        generated = []
        for t in tickers:
            try:
                out = generate_for_ticker(t, llm=args.deep_dive_llm, force=False)
                generated.append(str(out.name))
            except Exception as exc:
                log(f"Deep-dive {t} skip/fail: {exc}")
        summary["steps"].append({"deep_dives": generated})
        log(f"Deep-dives: {len(generated)} files")

    if not args.skip_paper:
        cfg = load_json(ROOT / "bot" / "config.json")
        signals = build_signals(cfg)
        ledger = load_ledger(cfg.get("starting_cash", 100000))
        dry = bool(args.paper_dry_run) or not bool(cfg.get("auto_paper", {}).get("enabled", True))
        result = apply_signals(ledger, signals, cfg, dry_run=dry)
        summary["steps"].append(
            {
                "paper": {
                    "dry_run": dry,
                    "halted": result.get("halted"),
                    "equity": result.get("equity"),
                    "cash": result.get("cash"),
                    "trades": len(result.get("applied") or []),
                    "applied": result.get("applied"),
                }
            }
        )
        log(f"Paper cycle dry_run={dry} trades={len(result.get('applied') or [])} equity={result.get('equity')}")

    out = LOG_DIR / f"cycle-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log(f"Wrote {out}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
