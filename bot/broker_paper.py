#!/usr/bin/env python3
"""Paper broker: simulated fills + JSON ledger. No live orders."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "bot" / "ledger" / "paper_ledger.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_ledger(starting_cash: float = 100000.0) -> dict:
    if LEDGER.exists():
        with LEDGER.open(encoding="utf-8") as f:
            return json.load(f)
    return {
        "cash": starting_cash,
        "starting_cash": starting_cash,
        "positions": {},
        "trades": [],
        "halted": False,
        "updated": _now(),
    }


def save_ledger(ledger: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    ledger["updated"] = _now()
    with LEDGER.open("w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2)
        f.write("\n")


def equity(ledger: dict, marks: dict[str, float]) -> float:
    eq = ledger["cash"]
    for t, pos in ledger["positions"].items():
        eq += pos["shares"] * marks.get(t, pos["avg_price"])
    return eq


def apply_signals(ledger: dict, signals: list[dict], cfg: dict, dry_run: bool = False) -> dict:
    if ledger.get("halted"):
        return {"halted": True, "applied": []}

    max_pos_pct = cfg.get("max_position_pct", 0.1)
    max_open = cfg.get("max_open_positions", 5)
    slip = cfg.get("slippage_bps", 5) / 10000.0
    applied = []
    marks = {s["ticker"]: float(s["price"]) for s in signals if s.get("price")}

    # Closes first
    for s in signals:
        if s["intent"] != "CLOSE_LONG":
            continue
        t = s["ticker"]
        if t not in ledger["positions"]:
            continue
        pos = ledger["positions"][t]
        px = float(s["price"]) * (1 - slip)
        proceeds = pos["shares"] * px
        trade = {
            "ts": _now(),
            "ticker": t,
            "side": "SELL",
            "shares": pos["shares"],
            "price": round(px, 4),
            "action": s["action"],
            "reason": "; ".join(s.get("reasons") or []),
        }
        if not dry_run:
            ledger["cash"] += proceeds
            del ledger["positions"][t]
            ledger["trades"].append(trade)
        applied.append(trade)

    eq = equity(ledger, marks)
    open_count = len(ledger["positions"])

    for s in signals:
        if s["intent"] != "OPEN_LONG":
            continue
        t = s["ticker"]
        if t in ledger["positions"]:
            continue
        if open_count >= max_open:
            break
        px = float(s["price"]) * (1 + slip)
        budget = eq * max_pos_pct
        shares = int(budget // px)
        if shares <= 0:
            continue
        cost = shares * px
        if cost > ledger["cash"]:
            continue
        trade = {
            "ts": _now(),
            "ticker": t,
            "side": "BUY",
            "shares": shares,
            "price": round(px, 4),
            "action": s["action"],
            "reason": "; ".join(s.get("reasons") or []),
        }
        if not dry_run:
            ledger["cash"] -= cost
            ledger["positions"][t] = {"shares": shares, "avg_price": round(px, 4)}
            ledger["trades"].append(trade)
            open_count += 1
        applied.append(trade)

    # Kill switch on marked equity
    start = ledger.get("starting_cash", eq)
    day_pnl_pct = (eq - start) / start * 100 if start else 0
    # Simplified: vs starting cash (full paper session). Live bot should use day-open equity.
    max_loss = cfg.get("kill_switch", {}).get("max_daily_loss_pct", 3.0)
    if day_pnl_pct <= -max_loss and cfg.get("kill_switch", {}).get("halt_on_trigger", True):
        ledger["halted"] = True
        applied.append({"ts": _now(), "event": "KILL_SWITCH", "pnl_pct": round(day_pnl_pct, 2)})

    if not dry_run:
        save_ledger(ledger)
    return {"halted": ledger.get("halted", False), "applied": applied, "equity": round(eq, 2), "cash": round(ledger["cash"], 2)}
