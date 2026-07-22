#!/usr/bin/env python3
"""Deterministic signal builder from Finwiz action ranks."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib_finwiz import load_json, rebuild_index  # noqa: E402

BOT_CFG = ROOT / "bot" / "config.json"


def build_signals(cfg: dict | None = None) -> list[dict]:
    cfg = cfg or load_json(BOT_CFG)
    index = rebuild_index()
    signals = []
    for d in index["docs"]:
        if cfg.get("only_gate_pass") and not d.get("passes_gate"):
            continue
        action = d.get("action")
        intent = None
        if action in cfg.get("open_on_actions", ["BUY"]):
            if d.get("scores", {}).get("composite", 0) < cfg.get("min_composite", 0):
                continue
            if (d.get("upside_pct") or -999) < cfg.get("min_upside_pct", 0):
                continue
            if d.get("recom") is not None and d["recom"] > cfg.get("max_recom", 99):
                continue
            intent = "OPEN_LONG"
        elif action in cfg.get("close_on_actions", ["SELL", "AVOID"]):
            intent = "CLOSE_LONG"
        elif action in cfg.get("hold_actions", ["HOLD"]):
            intent = "HOLD"
        if not intent:
            continue
        signals.append(
            {
                "ticker": d["ticker"],
                "intent": intent,
                "action": action,
                "analyst_label": d.get("analyst_label"),
                "recom": d.get("recom"),
                "upside_pct": d.get("upside_pct"),
                "composite": d.get("scores", {}).get("composite"),
                "price": d.get("metrics", {}).get("price"),
                "reasons": d.get("action_reasons", []),
            }
        )
    # Prefer strongest BUY first
    rank = {"OPEN_LONG": 3, "HOLD": 2, "CLOSE_LONG": 1}
    signals.sort(key=lambda s: (rank.get(s["intent"], 0), s.get("composite") or 0), reverse=True)
    return signals


if __name__ == "__main__":
    for s in build_signals():
        print(
            f"{s['ticker']:6} {s['intent']:11} action={s['action']:5} "
            f"recom={s['recom']} upside={s['upside_pct']}% comp={s['composite']}"
        )
