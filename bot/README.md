# Finwiz Trading Bot — Architecture (Paper-First)

This is how the Finwiz Screener becomes a **standalone, deterministic, AI-enabled trading bot** without letting an LLM place unsupervised live orders.

## Core principle

| Layer | Who decides? | Role |
|-------|--------------|------|
| **Screener + deep-dive gate** | Deterministic rules | Universe filter |
| **BUY/HOLD/SELL/AVOID** | Deterministic rules (`config/action.rules.json`) | Signal |
| **AI / NL query** | Optional LLM | Search, explain, rank — **never** submit orders |
| **Execution** | Broker adapter | Paper by default; live only with explicit unlock |

**Deterministic** = same inputs → same action. AI helps you *query and research*; it does **not** invent trade decisions at runtime.

## Pipeline

```
Finviz data (metrics, recom, SMAs, news)
        ↓
data/tickers/*.json  +  deep-dive gate
        ↓
compute_action() → BUY | HOLD | SELL | AVOID
        ↓
bot/signals.py → sized trade intents (paper)
        ↓
bot/broker_paper.py → fills + ledger
        ↓
[OPTIONAL] bot/broker_live.py  ← requires FINWIZ_LIVE_TRADING=1 + broker keys
```

## Safety gates (required before live)

1. `FINWIZ_LIVE_TRADING` must be exactly `1`
2. Broker API keys present
3. Max position % and daily loss kill-switch in `bot/config.json`
4. Only `action=BUY` can open; `SELL`/`AVOID` can only reduce/close
5. No market orders in v1 — limit/mid only in paper; live starts disabled

## How I can help you build it (phased)

| Phase | Deliverable | Status |
|-------|-------------|--------|
| **0** | Screener + action ranks + query | Done |
| **1** | Paper bot: signals → simulated fills → ledger | Scaffold in `bot/` |
| **2** | Backtest harness on historical Finviz snapshots / yfinance | Done — `scripts/backtest.py` (static fundamentals + historical timing) |
| **3** | Broker adapter (Alpaca Paper first) | **Next** — local paper does not hit Alpaca; MCP/LLM never submits orders |
| **4** | Live unlock with kill-switch + audit log | Explicit opt-in only |

**Agreed path:** local paper ledger → Alpaca Paper adapter → side-by-side → live only with `FINWIZ_LIVE_TRADING=1` + tiny size. Alpaca API keys today power **bars**, not trades.

## Run paper bot

```powershell
cd "D:\Finwiz Screener for Promising Growth Stocks"
py -3 scripts\rank_actions.py --gate-only
py -3 bot\run_paper.py --dry-run
py -3 bot\run_paper.py
```

## What “AI-enabled” means here

- Use `scripts\query.py` / optional `--llm` to **find and explain** candidates
- Bot **execution path** stays rule-based so you can audit every order
- If you later want AI to propose rule *changes*, treat that as a PR to `action.rules.json` — never hot-path into the broker

## Disclaimer

Not financial advice. Automated trading can lose money. Paper-trade until the ledger and kill-switches behave the way you expect.
