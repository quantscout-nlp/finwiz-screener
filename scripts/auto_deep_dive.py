#!/usr/bin/env python3
"""Generate a deep-dive markdown stub from ticker JSON (+ optional LLM polish)."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_finwiz import ROOT, TICKERS_DIR, load_json, save_json  # noqa: E402

DEEP = ROOT / "deep-dives"
TEMPLATE = ROOT / "templates" / "deep-dive.template.md"


def build_md(ticker_data: dict, event: str = "", consensus: str = "") -> str:
    t = ticker_data.get("ticker", "TICK")
    m = ticker_data.get("metrics") or {}
    tech = ticker_data.get("technicals") or {}
    news = ticker_data.get("news") or {}
    dd = ticker_data.get("deep_dive") or {}
    price = m.get("price")
    target = m.get("target_price")
    sma200 = tech.get("sma200_pct")
    catalyst = news.get("next_catalyst") or event or "TBD"
    cat_date = news.get("catalyst_date") or date.today().isoformat()

    support = round(float(price) * 0.92, 2) if price else ""
    pivot = round(float(price) * 0.98, 2) if price else ""
    resist = round(float(target) * 0.95, 2) if target else (round(float(price) * 1.08, 2) if price else "")

    bullets = "\n".join(f"- {b}" for b in (news.get("headline_bullets") or [])[:5]) or "- (add headlines)"

    return f"""# {t} → {cat_date}: Levels, History, Good vs Bad Print

**As of:** {date.today().isoformat()}  
**Event:** {catalyst}  
**Consensus:** {consensus or dd.get('included_reason', 'See Finwiz composite / analyst recom')}  
**Auto-generated:** yes (edit and refine before trading)

## Snapshot
- Price: {price} | Target: {target} | Recom: {m.get('recom')}
- Sales YoY: {m.get('sales_growth_yoy')}% | EPS YoY: {m.get('eps_growth_yoy')}% | PEG: {m.get('peg')}
- RSI: {tech.get('rsi14')} | vs SMA200: {sma200}% | Setup: {tech.get('setup', '')}
- News flow: {dd.get('news_flow')} | Technicals: {dd.get('technicals')}

## News bullets
{bullets}

## Levels

| Zone | Price | Role |
|------|-------|------|
| Resistance | {resist} | Near target / extension |
| Pivot | {pivot} | Near last close |
| Support | {support} | ~8% below last |

## Historical post-earnings moves

| Quarter | Day 0 | +5d | Note |
|---------|-------|-----|------|
| TBD | | | Fill from Finviz / transcript |

## Good vs bad print

### Good
- Beat + raise (or strong guide) with constructive tape above SMA200
- Upside to target remains attractive vs peers

### Bad
- Miss / guide cut with break of support {support}
- Recom / composite fails Tight BUY band

## Checklist
- [ ] Update `data/tickers/{t}.json` metrics from Finviz Elite sync
- [ ] Rebuild index: `py -3 scripts\\rebuild_index.py`
- [ ] Confirm levels against live chart
"""


def optional_llm_polish(md: str, ticker: str) -> str:
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("FINWIZ_LLM_API_KEY")
    if not key:
        return md
    try:
        from openai import OpenAI
    except ImportError:
        return md
    client = OpenAI(api_key=key)
    resp = client.chat.completions.create(
        model=os.environ.get("FINWIZ_LLM_MODEL", "gpt-4o-mini"),
        temperature=0.2,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Improve this earnings deep-dive for {ticker}. Keep markdown structure, "
                    "levels table, good/bad print, and checklist. Be concise and trading-desk tone.\n\n"
                    + md
                ),
            }
        ],
    )
    return resp.choices[0].message.content or md


def generate_for_ticker(ticker: str, *, llm: bool = False, force: bool = False) -> Path:
    path = TICKERS_DIR / f"{ticker.upper()}.json"
    if not path.exists():
        raise FileNotFoundError(f"No ticker profile: {path}")
    data = load_json(path)
    out = DEEP / f"{ticker.upper()}-auto-{date.today().isoformat()}.md"
    # Prefer stable name if catalyst date known
    cat = (data.get("news") or {}).get("catalyst_date")
    if cat:
        out = DEEP / f"{ticker.upper()}-{cat}.md"
    if out.exists() and not force:
        return out
    md = build_md(data)
    if llm:
        md = optional_llm_polish(md, ticker.upper())
    DEEP.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    data["deep_dive_path"] = str(out.relative_to(ROOT)).replace("\\", "/")
    data["updated"] = date.today().isoformat()
    save_json(path, data)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Auto-generate deep-dive markdown")
    p.add_argument("tickers", nargs="*", help="Tickers (default: all with catalyst_date)")
    p.add_argument("--all-core", action="store_true")
    p.add_argument("--llm", action="store_true", help="Polish with OpenAI if key set")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    tickers = [t.upper() for t in args.tickers]
    if args.all_core or not tickers:
        tickers = [p.stem for p in sorted(TICKERS_DIR.glob("*.json")) if not p.name.startswith("_")]

    for t in tickers:
        try:
            out = generate_for_ticker(t, llm=args.llm, force=args.force)
            print(f"OK {t} -> {out}")
        except Exception as exc:
            print(f"FAIL {t}: {exc}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
