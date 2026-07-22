# Finwiz Screener for Promising Growth Stocks

Local, expandable Finviz-powered growth screener with AI-queryable intelligence, **BUY/HOLD/SELL/AVOID** ranking, SMA ON/OFF toggles, a **capitulation** second screener, and a paper-first trading bot.

> **Finwiz** = this project. Data source = **Finviz** (finviz.com).

## LAUNCH COMMAND (AI searchable / queryable)

```powershell
cd "D:\Finwiz Screener for Promising Growth Stocks"
.\launch.ps1
```

Or:

```powershell
cd "D:\Finwiz Screener for Promising Growth Stocks"
py -3 scripts\query.py "growth stocks with strong news and workable technicals" --rebuild
```

Double-click / CMD:

```bat
D:\Finwiz Screener for Promising Growth Stocks\launch.cmd
```

With a custom query:

```powershell
.\launch.ps1 "action=BUY"
.\launch.ps1 "capitulation"
.\launch.ps1 "news_flow>=strong technicals>=workable"
```

## Toggles (ON/OFF + SMA selector)

```powershell
py -3 scripts\toggle.py
py -3 scripts\toggle.py --on
py -3 scripts\toggle.py --off
py -3 scripts\toggle.py --sma on --period 50
py -3 scripts\toggle.py --sma on --period 200
py -3 scripts\toggle.py --period 20
py -3 scripts\toggle.py --tight on
py -3 scripts\toggle.py --capitulation on
```

Allowed SMA periods: **9, 20, 50, 100, 200**.

Tight BUY (default ON): Strong Buy recom ≤ 1.5, upside ≥ 15%, composite ≥ 80, RSI 40–65, and price **above** selected SMA when SMA filter is ON.

## Capitulation / mean-reversion (second screener)

For active corrections with ~**5–50%** drawdowns over ~**30–90** days:

```powershell
py -3 scripts\screen_capitulation.py
py -3 scripts\query.py "capitulation"
```

## Finviz links — YOUR hits vs market discovery

**Wrong expectation:** market-wide Finviz filter URLs (387/900+ stocks) = your Finwiz picks.  
**Correct:** Finwiz first decides the tickers; Finviz opens with `&t=NVDA,TSM,...` so you only see those names.

```powershell
py -3 scripts\export_finviz_hits.py
py -3 scripts\build_watchlist_url.py --action BUY
py -3 scripts\build_watchlist_url.py --capitulation
```

That writes files like:
- `screeners\finwiz-buy-hits.url.txt`
- `screeners\YOUR_capitulation_hits_overview.url.txt`

Open those — the address bar must contain `&t=TSM,CRDO,AVGO` (or your BUY list), not only `&f=cap_largeover,...`.

## Hedge Fund Manager Dashboard (Streamlit)

Interactive multi-page dashboard that reads the same local index and ticker JSON as the CLI — action ranks, gate status, capitulation hits, deep dives, toggles, and Finviz export links.

```powershell
cd "D:\Finwiz Screener for Promising Growth Stocks"
.\launch_dashboard.ps1
```

Or:

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m streamlit run dashboard\app.py
```

Double-click / CMD:

```bat
launch_dashboard.cmd
```

Opens at **http://localhost:8501** with these pages:

| Page | Purpose |
|------|---------|
| **Command Center** | KPIs, action mix chart, composite vs upside scatter, top BUY cards |
| **Growth Screener** | Sortable/filterable table + ticker detail cards (mirrors CLI output) |
| **Capitulation** | Mean-reversion hits, drawdown chart, Finviz links |
| **Ticker Intel** | Full profile, news bullets, markdown deep dives |
| **Query Lab** | Same NL/structured query engine as `scripts/query.py` |
| **Controls & Export** | Toggle SMA/tight BUY/capitulation in UI, rebuild index, Finviz URLs |
| **Paper Trading** | Paper auto-trade cycle + ledger (simulated fills only) |

Sidebar + **Controls & Export**: switchable **SMA ON/OFF** and period **9 / 20 / 50 / 100 / 200**, plus **Tight BUY ON/OFF**.

### Always-on automation (Windows Task Scheduler)

```powershell
# Install background job (every 15 minutes): Elite sync → rebuild → deep-dive stubs → paper trades
.\scripts\install_scheduled_task.ps1
.\scripts\install_scheduled_task.ps1 -Minutes 15

# Run one cycle now
powershell -File .\scripts\run_automation.ps1
# or
py -3 scripts\automation_cycle.py --deep-dives

# Paper auto-trade only (writes ledger)
py -3 bot\run_paper.py

# Auto deep-dives / auto-add candidates
py -3 scripts\auto_deep_dive.py --all-core
py -3 scripts\auto_add_tickers.py --tickers AMD,ARM --status candidate

# Uninstall task
.\scripts\install_scheduled_task.ps1 -Uninstall
```

Logs: `data\automation_logs\`

### Live features

- **Auto-refresh** — sidebar toggle rebuilds the index every 30s–5m (rescoring all tickers)
- **Finviz Elite sync** — set `FINVIZ_API_KEY` (from [elite.finviz.com/api_explanation](https://elite.finviz.com/api_explanation)); auto-runs on rebuild/refresh
- **Price charts** — yfinance OHLC + SMA overlays + analyst target on Ticker Intel, Growth Screener, Query Lab
- **LLM rerank** — Query Lab checkbox; uses `OPENAI_API_KEY` or paste a key in-session (`gpt-4o-mini` default)
- **Paper auto-trade** — simulated BUY/SELL fills into `bot/ledger/paper_ledger.json` (not live broker)

### Environment variables (Windows)

```powershell
# Finviz Elite API token (Generate API Token on elite.finviz.com)
[Environment]::SetEnvironmentVariable("FINVIZ_API_KEY", "your-elite-token", "User")

# OpenAI (optional — Query Lab LLM rerank)
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "sk-...", "User")
```

Restart terminal/dashboard after setting. **Never commit keys to git.**

Manual Elite sync:

```powershell
py -3 scripts\sync_finviz_elite.py
```

**GitHub:** https://github.com/quantscout-nlp/finwiz-screener
