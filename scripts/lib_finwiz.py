"""Shared helpers for Finwiz Screener (stdlib-first)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TICKERS_DIR = ROOT / "data" / "tickers"
INDEX_PATH = ROOT / "data" / "index" / "search_index.json"
WEIGHTS_PATH = ROOT / "config" / "scoring.weights.json"
ACTION_RULES_PATH = ROOT / "config" / "action.rules.json"
TOGGLES_PATH = ROOT / "config" / "toggles.json"
WATCHLISTS_DIR = ROOT / "watchlists"

NEWS_RANK = {"weak": 1, "moderate": 2, "strong": 3, "exceptional": 4}
TECH_RANK = {"broken": 1, "fragile": 2, "workable": 3, "constructive": 4, "strong": 5}
ACTION_RANK = {"BUY": 4, "HOLD": 3, "SELL": 2, "AVOID": 1}
SMA_FIELD = {9: "sma9_pct", 20: "sma20_pct", 50: "sma50_pct", 100: "sma100_pct", 200: "sma200_pct"}


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def load_weights() -> dict:
    return load_json(WEIGHTS_PATH)


def load_action_rules() -> dict:
    return load_json(ACTION_RULES_PATH)


def load_toggles() -> dict:
    return load_json(TOGGLES_PATH)


def save_toggles(data: dict) -> None:
    save_json(TOGGLES_PATH, data)


def load_all_tickers() -> list[dict]:
    tickers = []
    if not TICKERS_DIR.exists():
        return tickers
    for path in sorted(TICKERS_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        tickers.append(load_json(path))
    return tickers


def analyst_label_from_recom(recom: float | None) -> str:
    if recom is None:
        return "Unknown"
    if recom < 1.5:
        return "Strong Buy"
    if recom < 2.5:
        return "Buy"
    if recom < 3.5:
        return "Hold"
    if recom < 4.5:
        return "Sell"
    return "Strong Sell"


def analyst_score_from_recom(recom: float | None) -> float:
    if recom is None:
        return 50.0
    return round(max(0.0, min(100.0, (5.0 - float(recom)) * 25.0)), 1)


def upside_pct(t: dict) -> float | None:
    m = t.get("metrics", {})
    price = m.get("price")
    target = m.get("target_price")
    if price is None or target is None or not price:
        return None
    return round((float(target) - float(price)) / float(price) * 100.0, 2)


def resolve_sma_pct(tech: dict, period: int) -> tuple[float | None, str, bool]:
    """Return (pct_vs_sma, source_label, used_proxy)."""
    period = int(period)
    field = SMA_FIELD.get(period)
    if not field:
        return None, f"sma{period}", False
    if tech.get(field) is not None:
        return float(tech[field]), field, False
    if period == 9 and tech.get("sma20_pct") is not None:
        return float(tech["sma20_pct"]), "sma20_pct(proxy_for_9)", True
    if period == 100:
        s50, s200 = tech.get("sma50_pct"), tech.get("sma200_pct")
        if s50 is not None and s200 is not None:
            return (float(s50) + float(s200)) / 2.0, "sma50_200_avg(proxy_for_100)", True
        if s50 is not None:
            return float(s50), "sma50_pct(proxy_for_100)", True
    return None, field, False


def score_ticker(t: dict, weights: dict | None = None) -> dict:
    weights = weights or load_weights()
    dd = t.get("deep_dive", {})
    news_label = dd.get("news_flow", "moderate")
    tech_label = dd.get("technicals", "workable")
    news_score = dd.get("scores", {}).get("news_flow") or weights["news_flow"].get(news_label, 50)
    tech_score = dd.get("scores", {}).get("technicals") or weights["technicals"].get(tech_label, 50)
    m = t.get("metrics", {})
    fund = dd.get("scores", {}).get("fundamentals")
    if fund is None:
        fund = 50
        if (m.get("sales_growth_yoy") or 0) >= 25:
            fund += 15
        if (m.get("eps_growth_yoy") or 0) >= 25:
            fund += 10
        if m.get("peg") is not None and m["peg"] < 1:
            fund += 10
        if (m.get("profit_margin") or 0) >= 20:
            fund += 10
        fund = min(fund, 100)
    recom = m.get("recom")
    analyst = dd.get("scores", {}).get("analyst")
    if analyst is None:
        analyst = analyst_score_from_recom(recom)
    c = weights["composite"]
    w_news = c.get("news_flow", 0.35)
    w_tech = c.get("technicals", 0.35)
    w_fund = c.get("fundamentals", 0.30)
    w_an = c.get("analyst", 0.0)
    total_w = w_news + w_tech + w_fund + w_an
    composite = round(
        (news_score * w_news + tech_score * w_tech + fund * w_fund + analyst * w_an) / total_w,
        1,
    )
    return {
        "news_flow": news_score,
        "technicals": tech_score,
        "fundamentals": fund,
        "analyst": analyst,
        "composite": composite,
    }


def passes_deep_dive_gate(t: dict, weights: dict | None = None) -> bool:
    weights = weights or load_weights()
    gate = weights["gate"]
    dd = t.get("deep_dive", {})
    if NEWS_RANK.get(dd.get("news_flow", "weak"), 0) < NEWS_RANK[gate["min_news_flow"]]:
        return False
    if TECH_RANK.get(dd.get("technicals", "broken"), 0) < TECH_RANK[gate["min_technicals"]]:
        return False
    scores = score_ticker(t, weights)
    return scores["composite"] >= gate["min_composite"]


def drawdown_window(tech: dict) -> dict:
    """Estimate 30d/90d drawdowns from Finviz perf month/quarter (negative = down)."""
    month = tech.get("perf_month")
    quarter = tech.get("perf_quarter")
    from_high = tech.get("from_52w_high_pct")
    d30 = abs(min(0.0, float(month))) if month is not None else None
    d90 = abs(min(0.0, float(quarter))) if quarter is not None else None
    worst = None
    for v in (d30, d90):
        if v is not None:
            worst = v if worst is None else max(worst, v)
    # Also consider 52w drawdown capped into correction band context
    from_high_dd = abs(min(0.0, float(from_high))) if from_high is not None else None
    return {
        "drawdown_30d_pct": d30,
        "drawdown_90d_pct": d90,
        "drawdown_worst_pct": worst,
        "from_52w_drawdown_pct": from_high_dd,
    }


def compute_capitulation(t: dict, toggles: dict | None = None) -> dict:
    """Mean-reversion / capitulation score for correction/oversold setups."""
    toggles = toggles or load_toggles()
    cap = toggles.get("capitulation_mode", {})
    tech = t.get("technicals", {})
    m = t.get("metrics", {})
    dd = drawdown_window(tech)
    rsi = tech.get("rsi14")
    recom = m.get("recom")
    period = int(cap.get("sma_period", 50))
    sma_pct, sma_src, _ = resolve_sma_pct(tech, period)
    dmin = float(cap.get("drawdown_min_pct", 5))
    dmax = float(cap.get("drawdown_max_pct", 50))
    rsi_max = float(cap.get("rsi_max", 40))
    worst = dd.get("drawdown_worst_pct")
    # Fallback: use 52w drawdown if month/quarter not down enough but correction is real
    if worst is None and dd.get("from_52w_drawdown_pct") is not None:
        worst = dd["from_52w_drawdown_pct"]

    in_band = worst is not None and dmin <= worst <= dmax
    # Also accept if month OR quarter alone is in band
    month_dd = dd.get("drawdown_30d_pct")
    quarter_dd = dd.get("drawdown_90d_pct")
    if not in_band:
        for v in (month_dd, quarter_dd):
            if v is not None and dmin <= v <= dmax:
                in_band = True
                worst = v
                break

    rsi_ok = rsi is not None and float(rsi) <= rsi_max
    below_sma = sma_pct is not None and sma_pct < 0
    quality = recom is not None and float(recom) <= float(cap.get("min_quality_recom", 2.5))

    reasons = []
    if in_band:
        reasons.append(f"drawdown ~{worst:.1f}% in 30–90d band")
    if rsi_ok:
        reasons.append(f"RSI {rsi} <= {rsi_max}")
    if below_sma:
        reasons.append(f"below SMA{period} ({sma_pct:.1f}% via {sma_src})")
    if quality:
        reasons.append(f"analyst quality recom {recom}")

    score = 0
    if in_band:
        score += 40
    if rsi_ok:
        score += 25
    if below_sma or not cap.get("prefer_below_sma", True):
        score += 20 if below_sma else 10
    if quality:
        score += 15

    passes = bool(
        cap.get("enabled", True)
        and in_band
        and (rsi_ok or below_sma)
        and quality
    )
    return {
        "passes": passes,
        "score": score,
        "drawdown_worst_pct": worst,
        "drawdown_30d_pct": month_dd,
        "drawdown_90d_pct": quarter_dd,
        "rsi14": rsi,
        "sma_period": period,
        "sma_pct": sma_pct,
        "reasons": reasons,
        "mode": "capitulation",
    }


def compute_action(t: dict, weights: dict | None = None, toggles: dict | None = None) -> dict:
    """Deterministic BUY / HOLD / SELL / AVOID from Finviz + deep-dive + toggles."""
    weights = weights or load_weights()
    toggles = toggles or load_toggles()
    m = t.get("metrics", {})
    tech = t.get("technicals", {})
    dd = t.get("deep_dive", {})
    recom = m.get("recom")
    rsi = tech.get("rsi14")
    tech_label = dd.get("technicals", "workable")
    scores = score_ticker(t, weights)
    gate_ok = passes_deep_dive_gate(t, weights)
    upside = upside_pct(t)
    reasons: list[str] = []

    sma_cfg = toggles.get("sma_filter", {})
    tight = toggles.get("tight_buy", {})
    sma_period = int(sma_cfg.get("period", 200))
    sma_pct, sma_src, sma_proxy = resolve_sma_pct(tech, sma_period)
    max_recom = float(tight.get("max_recom", 1.5)) if tight.get("enabled", True) else 2.0
    min_upside = float(tight.get("min_upside_pct", 15)) if tight.get("enabled", True) else 10.0
    min_comp = float(tight.get("min_composite", 80)) if tight.get("enabled", True) else 70.0
    rsi_min = float(tight.get("rsi_min", 40)) if tight.get("enabled", True) else 0.0
    rsi_max = float(tight.get("rsi_max", 65)) if tight.get("enabled", True) else 100.0

    def flag(name: str) -> bool:
        if name == "screener_disabled":
            hit = not toggles.get("screener_enabled", True)
            if hit:
                reasons.append("master screener toggle OFF")
            return hit
        if name == "growth_mode_enabled":
            hit = toggles.get("growth_mode", {}).get("enabled", True)
            if not hit:
                reasons.append("growth_mode OFF")
            return hit
        if name == "fails_deep_dive_gate":
            hit = not gate_ok
            if hit:
                reasons.append("fails deep-dive gate")
            return hit
        if name == "recom_gte_3.5":
            hit = recom is not None and float(recom) >= 3.5
            if hit:
                reasons.append(f"analyst recom {recom} (Sell zone)")
            return hit
        if name == "technicals_broken":
            hit = tech_label == "broken"
            if hit:
                reasons.append("technicals broken")
            return hit
        if name == "upside_lt_-20":
            hit = upside is not None and upside < -20
            if hit:
                reasons.append(f"upside to target {upside}%")
            return hit
        if name == "recom_gte_2.5_and_sma_filter_negative":
            hit = (
                recom is not None
                and float(recom) >= 2.5
                and sma_pct is not None
                and sma_pct < 0
            )
            if hit:
                reasons.append(f"recom {recom} + below SMA{sma_period} ({sma_pct:.1f}%)")
            return hit
        if name == "upside_lt_0_and_rsi_gt_70":
            hit = upside is not None and upside < 0 and rsi is not None and rsi > 70
            if hit:
                reasons.append(f"overbought RSI {rsi} with negative upside")
            return hit
        if name == "technicals_fragile_and_recom_gte_2.0":
            hit = tech_label == "fragile" and recom is not None and float(recom) >= 2.0
            if hit:
                reasons.append("fragile technicals + lukewarm analysts")
            return hit
        if name == "passes_deep_dive_gate":
            return gate_ok
        if name == "recom_lte_tight_max":
            hit = recom is not None and float(recom) <= max_recom
            if not hit:
                reasons.append(f"recom {recom} > tight max {max_recom}")
            return hit
        if name == "upside_gte_tight_min":
            hit = upside is not None and upside >= min_upside
            if not hit:
                reasons.append(f"upside {upside}% < tight min {min_upside}%")
            return hit
        if name == "technicals_workable_or_better":
            hit = TECH_RANK.get(tech_label, 0) >= TECH_RANK["workable"]
            if not hit:
                reasons.append(f"technicals {tech_label}")
            return hit
        if name == "composite_gte_tight_min":
            hit = scores["composite"] >= min_comp
            if not hit:
                reasons.append(f"composite {scores['composite']} < {min_comp}")
            return hit
        if name == "rsi_in_tight_band":
            if not tight.get("enabled", True):
                return True
            hit = rsi is not None and rsi_min <= float(rsi) <= rsi_max
            if not hit:
                reasons.append(f"RSI {rsi} outside {rsi_min}-{rsi_max}")
            return hit
        if name == "sma_filter_pass":
            if not sma_cfg.get("enabled", True):
                return True
            if sma_pct is None:
                reasons.append(f"SMA{sma_period} data missing")
                return False
            need_above = sma_cfg.get("require_above", True)
            hit = sma_pct > 0 if need_above else sma_pct < 0
            if not hit:
                reasons.append(f"fails SMA{sma_period} filter ({sma_pct:.1f}% via {sma_src})")
            return hit
        # legacy aliases
        if name == "recom_lte_2.0":
            return recom is not None and float(recom) <= 2.0
        if name == "upside_gte_10":
            return upside is not None and upside >= 10
        if name == "composite_gte_70":
            return scores["composite"] >= 70
        return False

    rules = load_action_rules()["rules"]

    for cond in rules["AVOID"]["any_of"]:
        if flag(cond):
            return _action_payload(
                "AVOID", recom, upside, scores, reasons, gate_ok, sma_period, sma_pct, sma_src, sma_proxy
            )

    sell_reasons: list[str] = []
    for cond in rules["SELL"]["any_of"]:
        before = len(reasons)
        if flag(cond):
            sell_reasons.extend(reasons[before:])
    if sell_reasons:
        return _action_payload(
            "SELL", recom, upside, scores, sell_reasons, gate_ok, sma_period, sma_pct, sma_src, sma_proxy
        )

    buy_ok = True
    buy_reasons: list[str] = []
    for cond in rules["BUY"]["all_of"]:
        before = len(reasons)
        if not flag(cond):
            buy_ok = False
            buy_reasons.extend(reasons[before:])
    if buy_ok:
        buy_reasons = [
            "passes deep-dive gate",
            f"analyst {analyst_label_from_recom(recom)} (recom {recom} <= {max_recom})",
            f"upside {upside}% >= {min_upside}%",
            f"SMA{sma_period} filter ON={sma_cfg.get('enabled')} ({sma_pct}% via {sma_src})",
            f"RSI {rsi} in {rsi_min}-{rsi_max}",
            f"composite {scores['composite']}",
        ]
        return _action_payload(
            "BUY", recom, upside, scores, buy_reasons, gate_ok, sma_period, sma_pct, sma_src, sma_proxy
        )

    hold_reasons = buy_reasons or ["mixed signals — watchlist / wait for catalyst"]
    if gate_ok and buy_reasons:
        hold_reasons = [f"gate PASS but misses BUY: {'; '.join(buy_reasons)}"]
    return _action_payload(
        "HOLD", recom, upside, scores, hold_reasons, gate_ok, sma_period, sma_pct, sma_src, sma_proxy
    )


def _action_payload(
    action: str,
    recom: float | None,
    upside: float | None,
    scores: dict,
    reasons: list[str],
    gate_ok: bool,
    sma_period: int,
    sma_pct: float | None,
    sma_src: str,
    sma_proxy: bool,
) -> dict:
    return {
        "action": action,
        "action_rank": ACTION_RANK[action],
        "analyst_label": analyst_label_from_recom(recom),
        "recom": recom,
        "upside_pct": upside,
        "gate_pass": gate_ok,
        "action_score": scores["composite"],
        "reasons": reasons[:6],
        "sma_period": sma_period,
        "sma_pct": sma_pct,
        "sma_source": sma_src,
        "sma_proxy": sma_proxy,
    }


def ticker_search_blob(t: dict) -> str:
    dd = t.get("deep_dive", {})
    action = compute_action(t)
    cap = compute_capitulation(t)
    parts = [
        t.get("ticker", ""),
        t.get("company", ""),
        t.get("sector", ""),
        t.get("industry", ""),
        dd.get("news_flow", ""),
        dd.get("technicals", ""),
        f"news_flow {dd.get('news_flow', '')}",
        f"technicals {dd.get('technicals', '')}",
        "strong news" if NEWS_RANK.get(dd.get("news_flow", ""), 0) >= NEWS_RANK["strong"] else "",
        "workable technicals" if TECH_RANK.get(dd.get("technicals", ""), 0) >= TECH_RANK["workable"] else "",
        action["action"],
        action["analyst_label"],
        f"action {action['action']}",
        f"analyst {action['analyst_label']}",
        "capitulation" if cap.get("passes") else "",
        "oversold mean reversion" if cap.get("passes") else "",
        dd.get("included_reason", ""),
        " ".join(t.get("tags", [])),
        " ".join(t.get("news", {}).get("headline_bullets", [])),
        t.get("news", {}).get("next_catalyst", ""),
        t.get("technicals", {}).get("setup", ""),
        json.dumps(t.get("metrics", {})),
    ]
    return " ".join(str(p) for p in parts).lower()


def rebuild_index() -> dict:
    weights = load_weights()
    toggles = load_toggles()
    docs = []
    for t in load_all_tickers():
        scores = score_ticker(t, weights)
        action = compute_action(t, weights, toggles)
        cap = compute_capitulation(t, toggles)
        docs.append(
            {
                "ticker": t["ticker"],
                "company": t.get("company"),
                "status": t.get("status"),
                "news_flow": t.get("deep_dive", {}).get("news_flow"),
                "technicals_label": t.get("deep_dive", {}).get("technicals"),
                "scores": scores,
                "passes_gate": passes_deep_dive_gate(t, weights),
                "action": action["action"],
                "action_rank": action["action_rank"],
                "analyst_label": action["analyst_label"],
                "recom": action["recom"],
                "upside_pct": action["upside_pct"],
                "action_reasons": action["reasons"],
                "sma_period": action.get("sma_period"),
                "sma_pct": action.get("sma_pct"),
                "capitulation": cap,
                "capitulation_pass": cap.get("passes"),
                "tags": t.get("tags", []),
                "metrics": t.get("metrics", {}),
                "technicals": t.get("technicals", {}),
                "news": t.get("news", {}),
                "deep_dive_path": t.get("deep_dive_path"),
                "finviz_url": t.get("finviz_url"),
                "blob": ticker_search_blob(t),
                "toggles": {
                    "screener_enabled": toggles.get("screener_enabled"),
                    "sma_filter": toggles.get("sma_filter"),
                    "tight_buy": toggles.get("tight_buy", {}).get("enabled"),
                    "capitulation_mode": toggles.get("capitulation_mode", {}).get("enabled"),
                },
            }
        )
    docs.sort(key=lambda d: (d.get("action_rank", 0), d.get("scores", {}).get("composite", 0)), reverse=True)
    index = {
        "updated": __import__("datetime").date.today().isoformat(),
        "count": len(docs),
        "toggles": toggles,
        "docs": docs,
    }
    save_json(INDEX_PATH, index)
    return index


def parse_structured_query(q: str) -> list[tuple[str, str, Any]]:
    clauses: list[tuple[str, str, Any]] = []
    pattern = re.compile(
        r"(news_flow|technicals|status|tag|sales_growth_yoy|eps_growth_yoy|peg|forward_pe|"
        r"rsi14|sma200_pct|sma50_pct|sma20_pct|perf_ytd|perf_month|perf_quarter|composite|"
        r"passes_gate|action|recom|upside_pct|analyst_label|action_rank|capitulation_pass|"
        r"mode|drawdown)\s*(>=|<=|=|>|<)\s*([^\s]+)",
        re.I,
    )
    for m in pattern.finditer(q):
        field, op, raw = m.group(1).lower(), m.group(2), m.group(3)
        if raw.lower() in ("true", "false"):
            val: Any = raw.lower() == "true"
        else:
            try:
                val = float(raw)
            except ValueError:
                if field == "action":
                    val = raw.upper()
                elif field == "analyst_label":
                    val = raw.replace("_", " ")
                else:
                    val = raw.lower()
        clauses.append((field, op, val))
    return clauses


def _cmp(left: Any, op: str, right: Any) -> bool:
    if left is None:
        return False
    if op == "=":
        if isinstance(right, str) and isinstance(left, str):
            return left.lower() == right.lower()
        return left == right
    try:
        lnum, rnum = float(left), float(right)
    except (TypeError, ValueError):
        if op == ">=" and isinstance(left, str) and isinstance(right, str):
            if left.upper() in ACTION_RANK and right.upper() in ACTION_RANK:
                return ACTION_RANK[left.upper()] >= ACTION_RANK[right.upper()]
            table = NEWS_RANK if left in NEWS_RANK else TECH_RANK
            return table.get(left, 0) >= table.get(right, 0)
        return False
    return {">": lnum > rnum, "<": lnum < rnum, ">=": lnum >= rnum, "<=": lnum <= rnum}[op]


def match_doc(doc: dict, clauses: list[tuple[str, str, Any]], free_text: str) -> bool:
    for field, op, val in clauses:
        if field == "news_flow":
            left = doc.get("news_flow")
        elif field == "technicals":
            left = doc.get("technicals_label")
        elif field == "status":
            left = doc.get("status")
        elif field == "tag":
            tags = [x.lower() for x in doc.get("tags", [])]
            if op == "=" and str(val).lower() in tags:
                continue
            return False
        elif field == "composite":
            left = doc.get("scores", {}).get("composite")
        elif field == "passes_gate":
            left = doc.get("passes_gate")
        elif field == "action":
            left = doc.get("action")
        elif field == "action_rank":
            left = doc.get("action_rank")
        elif field == "recom":
            left = doc.get("recom")
        elif field == "upside_pct":
            left = doc.get("upside_pct")
        elif field == "analyst_label":
            left = doc.get("analyst_label")
        elif field == "capitulation_pass":
            left = doc.get("capitulation_pass")
        elif field == "mode":
            if str(val).lower() in ("capitulation", "oversold", "mean_reversion"):
                left = doc.get("capitulation_pass")
                val = True
                op = "="
            else:
                left = "growth"
                val = str(val).lower()
        elif field == "drawdown":
            left = (doc.get("capitulation") or {}).get("drawdown_worst_pct")
        elif field in ("sales_growth_yoy", "eps_growth_yoy", "peg", "forward_pe"):
            left = doc.get("metrics", {}).get(field)
        elif field in ("rsi14", "sma200_pct", "sma50_pct", "sma20_pct", "perf_ytd", "perf_month", "perf_quarter"):
            left = doc.get("technicals", {}).get(field)
        else:
            left = None
        if not _cmp(left, op, val):
            return False

    if free_text.strip() and not clauses:
        residual = re.sub(
            r"(news_flow|technicals|status|tag|sales_growth_yoy|eps_growth_yoy|peg|forward_pe|"
            r"rsi14|sma200_pct|sma50_pct|sma20_pct|perf_ytd|perf_month|perf_quarter|composite|"
            r"passes_gate|action|recom|upside_pct|analyst_label|action_rank|capitulation_pass|"
            r"mode|drawdown)\s*(>=|<=|=|>|<)\s*[^\s]+",
            " ",
            free_text,
            flags=re.I,
        )
        tokens = [t for t in re.split(r"\W+", residual.lower()) if len(t) > 2]
        stop = {"with", "and", "the", "for", "that", "have", "which", "names", "stocks", "growth"}
        tokens = [t for t in tokens if t not in stop]
        blob = doc.get("blob", "")
        if tokens:
            hits = sum(1 for tok in tokens if tok in blob)
            if hits < max(1, len(tokens) // 2):
                return False
    return True


def apply_nl_hints(q: str) -> list[tuple[str, str, Any]]:
    ql = q.lower()
    clauses: list[tuple[str, str, Any]] = []
    if "strong news" in ql or "news flow" in ql:
        clauses.append(("news_flow", ">=", "strong"))
    if "workable technical" in ql or "workable technicals" in ql:
        clauses.append(("technicals", ">=", "workable"))
    if "promising" in ql or "core" in ql:
        clauses.append(("passes_gate", "=", True))
    if "earnings soon" in ql or "near-term catalyst" in ql:
        clauses.append(("tag", "=", "earnings-soon"))
    if "capitulation" in ql or "oversold" in ql or "mean reversion" in ql:
        clauses.append(("capitulation_pass", "=", True))
    if re.search(r"\bbuy\b", ql) and "sell" not in ql and "capitulation" not in ql:
        clauses.append(("action", "=", "BUY"))
    if re.search(r"\bhold\b", ql):
        clauses.append(("action", "=", "HOLD"))
    if re.search(r"\bsell\b", ql):
        clauses.append(("action", "=", "SELL"))
    if re.search(r"\bavoid\b", ql):
        clauses.append(("action", "=", "AVOID"))
    if "strong buy" in ql or "analyst buy" in ql:
        clauses.append(("recom", "<=", 1.5))
    return clauses
