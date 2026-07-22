#!/usr/bin/env python3
"""AI-powered searchable / queryable Finwiz screener CLI.

Examples:
  py -3 scripts/query.py "growth stocks with strong news and workable technicals"
  py -3 scripts/query.py "action=BUY recom<=2.0"
  py -3 scripts/query.py "buy" --limit 10
  py -3 scripts/query.py "promising growth" --llm
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_finwiz import (  # noqa: E402
    INDEX_PATH,
    ROOT,
    apply_nl_hints,
    match_doc,
    parse_structured_query,
    rebuild_index,
)


def load_index() -> dict:
    if not INDEX_PATH.exists():
        return rebuild_index()
    with INDEX_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def rank_docs(docs: list[dict], query: str) -> list[dict]:
    ql = query.lower()
    ranked = []
    for d in docs:
        # Prefer action rank, then composite
        score = d.get("action_rank", 0) * 100 + d.get("scores", {}).get("composite", 0)
        blob = d.get("blob", "")
        for tok in set(ql.split()):
            if len(tok) > 2 and tok in blob:
                score += 2
        if d.get("passes_gate"):
            score += 5
        ranked.append((score, d))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in ranked]


def optional_llm_rerank(docs: list[dict], query: str) -> list[dict] | None:
    api_key = os.environ.get("FINWIZ_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        print("openai package not installed; using local ranking.", file=sys.stderr)
        return None

    client = OpenAI(api_key=api_key)
    brief = [
        {
            "ticker": d["ticker"],
            "action": d.get("action"),
            "analyst": d.get("analyst_label"),
            "recom": d.get("recom"),
            "news_flow": d.get("news_flow"),
            "technicals": d.get("technicals_label"),
            "composite": d.get("scores", {}).get("composite"),
            "upside_pct": d.get("upside_pct"),
        }
        for d in docs[:20]
    ]
    prompt = (
        "Rank promising growth stocks. Prefer BUY actions, Strong Buy/Buy analyst labels, "
        "strong news flow, workable technicals, and positive upside to target. "
        f"Query: {query}\nCandidates JSON:\n{json.dumps(brief, indent=2)}\n"
        "Return ONLY a JSON array of tickers best-first."
    )
    resp = client.chat.completions.create(
        model=os.environ.get("FINWIZ_LLM_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    text = resp.choices[0].message.content or "[]"
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < 0:
        return None
    order = json.loads(text[start : end + 1])
    by_t = {d["ticker"]: d for d in docs}
    return [by_t[t] for t in order if t in by_t] + [d for d in docs if d["ticker"] not in order]


def format_doc(d: dict) -> str:
    m = d.get("metrics", {})
    tech = d.get("technicals", {})
    news = d.get("news", {})
    action = d.get("action", "?")
    lines = [
        f"## {d['ticker']} — {d.get('company')}",
        f"**ACTION: {action}** | Analyst: {d.get('analyst_label')} (recom {d.get('recom')}) | "
        f"Upside: {d.get('upside_pct')}%",
        f"Status: {d.get('status')} | Gate: {'PASS' if d.get('passes_gate') else 'FAIL'} | "
        f"Composite: {d.get('scores', {}).get('composite')} | "
        f"SMA{d.get('sma_period')}: {d.get('sma_pct')}%",
        f"Capitulation: {'YES' if d.get('capitulation_pass') else 'no'} "
        f"(dd={((d.get('capitulation') or {}).get('drawdown_worst_pct'))}%)",
        f"Deep-dive: news_flow={d.get('news_flow')} | technicals={d.get('technicals_label')}",
        f"Growth: sales YoY {m.get('sales_growth_yoy')}% | EPS YoY {m.get('eps_growth_yoy')}% | "
        f"PEG {m.get('peg')} | Fwd P/E {m.get('forward_pe')}",
        f"Technicals: RSI {tech.get('rsi14')} | vs SMA200 {tech.get('sma200_pct')}% | "
        f"YTD {tech.get('perf_ytd')}% | {tech.get('setup')}",
        f"Reasons: {'; '.join(d.get('action_reasons') or [])}",
        f"Catalyst: {news.get('next_catalyst')} ({news.get('catalyst_date')})",
        f"Finviz: {d.get('finviz_url')}",
    ]
    if d.get("deep_dive_path"):
        lines.append(f"Deep dive: {ROOT / d['deep_dive_path']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Query Finwiz promising growth tickers")
    parser.add_argument("query", nargs="+", help="Natural language and/or structured filters")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--rebuild", action="store_true", help="Rebuild index before query")
    parser.add_argument("--llm", action="store_true", help="Optional LLM re-rank if API key set")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()
    query = " ".join(args.query)

    if args.rebuild:
        rebuild_index()
    index = load_index()
    docs = index.get("docs", [])

    clauses = parse_structured_query(query) + apply_nl_hints(query)
    seen = set()
    uniq = []
    for c in clauses:
        if c[0] in seen:
            continue
        seen.add(c[0])
        uniq.append(c)

    filtered = [d for d in docs if match_doc(d, uniq, query)]
    if not filtered and uniq:
        filtered = [d for d in docs if match_doc(d, [], query)]

    ranked = rank_docs(filtered or docs, query)
    if args.llm:
        llm_ranked = optional_llm_rerank(ranked, query)
        if llm_ranked:
            ranked = llm_ranked

    top = ranked[: args.limit]
    if args.json:
        print(json.dumps(top, indent=2))
    else:
        print(f"Query: {query}")
        print(f"Matches: {len(ranked)} (showing {len(top)}) | Index: {index.get('updated')}\n")
        for d in top:
            print(format_doc(d))
            print("-" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
