"""Optional LLM rerank for dashboard Query Lab (same logic as scripts/query.py)."""

from __future__ import annotations

import json
import os
from typing import Any


def llm_rerank(
    docs: list[dict],
    query: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
) -> tuple[list[dict] | None, str | None]:
    """Return (reranked_docs, error_message). error_message is set when rerank unavailable."""
    key = api_key or os.environ.get("FINWIZ_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        return None, "No API key — set OPENAI_API_KEY or enter one below."

    try:
        from openai import OpenAI
    except ImportError:
        return None, "openai package not installed. Run: pip install openai"

    client = OpenAI(api_key=key)
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
    try:
        resp = client.chat.completions.create(
            model=model or os.environ.get("FINWIZ_LLM_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
    except Exception as exc:
        return None, f"OpenAI API error: {exc}"

    text = resp.choices[0].message.content or "[]"
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < 0:
        return None, "LLM returned invalid JSON (no ticker array)."

    try:
        order: list[Any] = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None, "LLM returned malformed JSON."

    by_t = {d["ticker"]: d for d in docs}
    ranked = [by_t[t] for t in order if isinstance(t, str) and t in by_t]
    ranked += [d for d in docs if d["ticker"] not in order]
    return ranked, None
