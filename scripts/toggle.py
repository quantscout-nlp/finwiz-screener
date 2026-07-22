#!/usr/bin/env python3
"""ON/OFF toggles + SMA period selector for Finwiz Screener.

Examples:
  py -3 scripts\\toggle.py
  py -3 scripts\\toggle.py --off
  py -3 scripts\\toggle.py --on
  py -3 scripts\\toggle.py --sma on --period 50
  py -3 scripts\\toggle.py --sma off
  py -3 scripts\\toggle.py --tight on
  py -3 scripts\\toggle.py --capitulation on
  py -3 scripts\\toggle.py --period 200
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_finwiz import load_toggles, rebuild_index, save_toggles  # noqa: E402

ALLOWED = {9, 20, 50, 100, 200}


def _parse_on_off(raw: str | None) -> bool | None:
    if raw is None:
        return None
    v = raw.strip().lower()
    if v in ("on", "1", "true", "yes", "enable", "enabled"):
        return True
    if v in ("off", "0", "false", "no", "disable", "disabled"):
        return False
    raise SystemExit(f"Invalid on/off value: {raw} (use on|off)")


def main() -> int:
    p = argparse.ArgumentParser(description="Finwiz screener toggles")
    p.add_argument("--on", action="store_true", help="Master screener ON")
    p.add_argument("--off", action="store_true", help="Master screener OFF")
    p.add_argument("--sma", choices=["on", "off"], help="SMA filter toggle")
    p.add_argument("--period", type=int, choices=sorted(ALLOWED), help="SMA period 9|20|50|100|200")
    p.add_argument("--tight", choices=["on", "off"], help="Tight BUY rules toggle")
    p.add_argument("--growth", choices=["on", "off"], help="Growth mode toggle")
    p.add_argument("--capitulation", choices=["on", "off"], help="Capitulation second screener")
    p.add_argument("--no-rebuild", action="store_true")
    args = p.parse_args()

    t = load_toggles()
    changed = False

    if args.on and args.off:
        raise SystemExit("Use only one of --on / --off")
    if args.on:
        t["screener_enabled"] = True
        changed = True
    if args.off:
        t["screener_enabled"] = False
        changed = True

    sma_state = _parse_on_off(args.sma)
    if sma_state is not None:
        t.setdefault("sma_filter", {})["enabled"] = sma_state
        changed = True
    if args.period is not None:
        t.setdefault("sma_filter", {})["period"] = args.period
        changed = True

    for key, flag in (
        ("tight_buy", args.tight),
        ("growth_mode", args.growth),
        ("capitulation_mode", args.capitulation),
    ):
        state = _parse_on_off(flag)
        if state is not None:
            t.setdefault(key, {})["enabled"] = state
            changed = True

    if changed:
        from datetime import date

        t["updated"] = date.today().isoformat()
        save_toggles(t)
        print("Saved config/toggles.json")
        if not args.no_rebuild:
            rebuild_index()
            print("Index rebuilt with new toggle state")
    else:
        print("Current toggles (no changes):")

    sma = t.get("sma_filter", {})
    print(f"  screener_enabled : {t.get('screener_enabled')}")
    print(f"  growth_mode      : {t.get('growth_mode', {}).get('enabled')}")
    print(f"  sma_filter       : {sma.get('enabled')}  period={sma.get('period')}")
    print(f"  tight_buy        : {t.get('tight_buy', {}).get('enabled')}")
    print(f"  capitulation     : {t.get('capitulation_mode', {}).get('enabled')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
