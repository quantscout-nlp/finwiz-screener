"""Retro backtest engine: yfinance history + Finwiz BUY/HOLD technical rules.

Limitation (documented): Finviz fundamentals (recom, upside, composite, news_flow)
are not available historically in this repo. Default mode applies *current* ticker
fundamentals as a static eligibility filter, then times entries/exits with
historical RSI / SMA / drawdown rules — a realistic heads-up, not a pure
point-in-time Finviz replay.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from lib_finwiz import (
    ROOT,
    TICKERS_DIR,
    load_all_tickers,
    load_json,
    load_toggles,
    upside_pct,
)

BACKTEST_DIR = ROOT / "data" / "backtests"


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def fetch_history(ticker: str, start: str, end: str | None = None, provider: str = "auto") -> pd.DataFrame:
    try:
        from lib_market_data import fetch_daily_bars

        df, _used = fetch_daily_bars(ticker, start, end, provider=provider)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    # Legacy yfinance-only fallback
    import yfinance as yf

    raw = yf.download(
        ticker,
        start=start,
        end=end,
        progress=False,
        auto_adjust=True,
        threads=False,
    )
    if raw is None or raw.empty:
        return pd.DataFrame()
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]) for c in df.columns]
    df = df.reset_index()
    date_col = "Date" if "Date" in df.columns else df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col]).dt.tz_localize(None)
    df = df.rename(columns={date_col: "Date"})
    close = df["Close"] if "Close" in df.columns else None
    if close is None:
        return pd.DataFrame()
    out = pd.DataFrame({"Date": df["Date"], "Close": close.astype(float)})
    out = out.dropna().sort_values("Date").reset_index(drop=True)
    return out


def enrich_technicals(df: pd.DataFrame, sma_period: int = 200) -> pd.DataFrame:
    out = df.copy()
    out["rsi14"] = _rsi(out["Close"], 14)
    for p in (9, 20, 50, 100, 200):
        out[f"sma{p}"] = out["Close"].rolling(p).mean()
        out[f"sma{p}_pct"] = (out["Close"] / out[f"sma{p}"] - 1.0) * 100.0
    out["perf_month"] = out["Close"].pct_change(21) * 100.0
    out["perf_quarter"] = out["Close"].pct_change(63) * 100.0
    out["dd_30d"] = -out["Close"].pct_change(21).clip(upper=0) * 100.0
    # use rolling max drawdown style for 30d window
    roll_max_21 = out["Close"].rolling(21, min_periods=5).max()
    out["dd_30d"] = ((roll_max_21 - out["Close"]) / roll_max_21 * 100.0).clip(lower=0)
    roll_max_63 = out["Close"].rolling(63, min_periods=10).max()
    out["dd_90d"] = ((roll_max_63 - out["Close"]) / roll_max_63 * 100.0).clip(lower=0)
    key = f"sma{sma_period}_pct"
    if key not in out.columns:
        key = "sma200_pct"
    out["sma_pct"] = out[key]
    return out


def static_eligibility(ticker_doc: dict, toggles: dict) -> dict[str, Any]:
    """Apply current Finviz/deep-dive fields as static gate (not point-in-time)."""
    from lib_finwiz import passes_deep_dive_gate, score_ticker, load_weights

    weights = load_weights()
    tight = toggles.get("tight_buy", {})
    m = ticker_doc.get("metrics") or {}
    dd = ticker_doc.get("deep_dive") or {}
    recom = m.get("recom")
    upside = upside_pct(ticker_doc)
    scores = score_ticker(ticker_doc, weights)
    gate = passes_deep_dive_gate(ticker_doc, weights)
    max_recom = float(tight.get("max_recom", 1.5)) if tight.get("enabled", True) else 2.0
    min_upside = float(tight.get("min_upside_pct", 15)) if tight.get("enabled", True) else 10.0
    min_comp = float(tight.get("min_composite", 80)) if tight.get("enabled", True) else 70.0
    tech_ok = dd.get("technicals") in ("workable", "constructive", "strong")
    ok = bool(
        gate
        and recom is not None
        and float(recom) <= max_recom
        and upside is not None
        and float(upside) >= min_upside
        and scores.get("composite", 0) >= min_comp
        and tech_ok
    )
    return {
        "eligible": ok,
        "recom": recom,
        "upside_pct": upside,
        "composite": scores.get("composite"),
        "gate": gate,
        "technicals_label": dd.get("technicals"),
        "news_flow": dd.get("news_flow"),
    }


def daily_signal(
    row: pd.Series,
    toggles: dict,
    eligible: bool,
    *,
    fundamentals_mode: str = "static",
) -> str:
    """Return BUY / HOLD / SELL / AVOID for one day."""
    if fundamentals_mode in ("static", "pit") and not eligible:
        return "AVOID"

    tight = toggles.get("tight_buy", {})
    sma_cfg = toggles.get("sma_filter", {})
    rsi_min = float(tight.get("rsi_min", 40)) if tight.get("enabled", True) else 0.0
    rsi_max = float(tight.get("rsi_max", 65)) if tight.get("enabled", True) else 100.0
    rsi = row.get("rsi14")
    sma_pct = row.get("sma_pct")
    sma_on = bool(sma_cfg.get("enabled", True))
    require_above = bool(sma_cfg.get("require_above", True))

    if pd.isna(rsi) or pd.isna(sma_pct):
        return "HOLD"

    # SELL-ish: below SMA when filter on, or RSI overbought
    if sma_on and require_above and float(sma_pct) < 0:
        return "SELL"
    if float(rsi) > 70:
        return "SELL"

    buy_rsi = rsi_min <= float(rsi) <= rsi_max
    buy_sma = (not sma_on) or (float(sma_pct) > 0)
    needs_elig = fundamentals_mode in ("static", "pit")
    if buy_rsi and buy_sma and (not needs_elig or eligible):
        return "BUY"
    return "HOLD"


@dataclass
class BacktestConfig:
    start: str = "2016-01-01"
    end: str | None = None
    starting_cash: float = 100_000.0
    max_position_pct: float = 0.10
    max_open_positions: int = 5
    slippage_bps: float = 5.0
    fundamentals_mode: str = "static"  # static | technicals_only | pit
    rebalance: str = "signal"  # signal-driven entries/exits
    price_provider: str = "auto"  # auto | lean | massive | alpaca | tiingo | yfinance
    bar_resolution: str = "Day"  # Day | 1Hour | 15Min | 5Min | 1Min (intraday resampled to daily signals)
@dataclass
class BacktestResult:
    summary: dict[str, Any] = field(default_factory=dict)
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    trades: list[dict] = field(default_factory=list)
    per_ticker: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def run_backtest(
    tickers: list[str] | None = None,
    cfg: BacktestConfig | None = None,
    toggles: dict | None = None,
) -> BacktestResult:
    cfg = cfg or BacktestConfig()
    toggles = toggles or load_toggles()
    docs = {t["ticker"].upper(): t for t in load_all_tickers()}
    if tickers:
        names = [t.upper() for t in tickers]
    else:
        names = sorted(docs.keys())

    sma_period = int(toggles.get("sma_filter", {}).get("period", 200))
    result = BacktestResult()
    result.notes.append(
        "Fundamentals modes: static=current Finwiz JSON; technicals_only=ignore fundamentals; "
        "pit=Massive/Benzinga ratings+income (+ LeanData statements fallback) as point-in-time eligibility."
    )
    result.notes.append(f"Price provider={cfg.price_provider} resolution={cfg.bar_resolution}")
    result.notes.append(f"SMA filter period={sma_period} enabled={toggles.get('sma_filter', {}).get('enabled')}")
    result.notes.append(f"Tight BUY enabled={toggles.get('tight_buy', {}).get('enabled')}")

    histories: dict[str, pd.DataFrame] = {}
    eligibility: dict[str, dict] = {}
    pit_elig: dict[str, pd.DataFrame] = {}
    for name in names:
        doc = docs.get(name) or {"ticker": name, "metrics": {}, "deep_dive": {}, "technicals": {}}
        elig = static_eligibility(doc, toggles) if doc.get("metrics") else {"eligible": True}
        eligibility[name] = elig
        if cfg.fundamentals_mode == "static" and doc.get("metrics") and not elig["eligible"]:
            result.per_ticker[name] = {"skipped": True, "reason": "fails static fundamental eligibility", **elig}
            continue
        # Prefer LeanData for multi-resolution; fetch_history uses provider auto chain
        try:
            from lib_market_data import fetch_daily_bars

            hist, used = fetch_daily_bars(
                name, cfg.start, cfg.end, provider=cfg.price_provider, resolution=cfg.bar_resolution
            )
        except Exception:
            hist, used = fetch_history(name, cfg.start, cfg.end, provider=cfg.price_provider), cfg.price_provider
        if hist is None or hist.empty:
            hist = fetch_history(name, cfg.start, cfg.end, provider=cfg.price_provider)
            used = cfg.price_provider
        # Resample intraday → daily close for SMA200/RSI signal engine
        if not hist.empty and cfg.bar_resolution != "Day":
            tmp = hist.copy()
            tmp = tmp.set_index("Date").sort_index()
            hist = tmp["Close"].resample("1D").last().dropna().reset_index()
            hist.columns = ["Date", "Close"]
        if hist.empty or len(hist) < 220:
            result.per_ticker[name] = {"skipped": True, "reason": "insufficient price history", "provider": used}
            continue
        histories[name] = enrich_technicals(hist, sma_period)
        meta = {"skipped": False, **elig, "bars": len(histories[name]), "provider": used}
        if cfg.fundamentals_mode == "pit":
            try:
                from lib_pit_eligibility import build_pit_eligibility_series, load_pit_bundle

                bundle = load_pit_bundle(name, cfg.start, cfg.end)
                pit = build_pit_eligibility_series(
                    name,
                    histories[name][["Date", "Close"]],
                    toggles,
                    ratings=bundle.get("ratings"),
                    income=bundle.get("income"),
                )
                pit_elig[name] = pit.set_index("Date")
                meta["pit_ratings_rows"] = bundle.get("ratings_rows")
                meta["pit_income_rows"] = bundle.get("income_rows")
                meta["pit_eligible_days"] = int(pit["eligible"].sum()) if not pit.empty else 0
            except Exception as exc:
                meta["pit_error"] = str(exc)
                pit_elig[name] = pd.DataFrame()
        result.per_ticker[name] = meta
    if not histories:
        result.summary = {"ok": False, "error": "No tickers with tradeable history"}
        return result

    # Align on common calendar (outer join of dates, forward fill prices)
    all_dates = sorted(set().union(*[set(df["Date"]) for df in histories.values()]))
    price_panel = pd.DataFrame({"Date": all_dates})
    signal_panel: dict[str, pd.Series] = {}
    close_panel: dict[str, pd.Series] = {}

    for name, df in histories.items():
        merged = price_panel.merge(df, on="Date", how="left")
        merged["Close"] = merged["Close"].ffill()
        for col in ("rsi14", "sma_pct"):
            if col in merged.columns:
                merged[col] = merged[col].ffill()
        signals = []
        for _, row in merged.iterrows():
            elig = eligibility.get(name, {}).get("eligible", True)
            if cfg.fundamentals_mode == "technicals_only":
                elig = True
            elif cfg.fundamentals_mode == "pit":
                pit = pit_elig.get(name)
                elig = False
                if pit is not None and not pit.empty:
                    ts = pd.Timestamp(row["Date"])
                    if ts in pit.index:
                        elig = bool(pit.loc[ts, "eligible"])
                    else:
                        # nearest prior date
                        prior = pit.index[pit.index <= ts]
                        if len(prior):
                            elig = bool(pit.loc[prior[-1], "eligible"])
            signals.append(
                daily_signal(
                    row,
                    toggles,
                    elig,
                    fundamentals_mode=cfg.fundamentals_mode,
                )
            )
        signal_panel[name] = pd.Series(signals, index=merged["Date"])
        close_panel[name] = pd.Series(merged["Close"].values, index=merged["Date"])

    cash = cfg.starting_cash
    positions: dict[str, dict] = {}
    trades: list[dict] = []
    equity_rows: list[dict] = []
    slip = cfg.slippage_bps / 10000.0

    for dt in all_dates:
        # Exits first
        for name in list(positions.keys()):
            sig = signal_panel[name].get(dt, "HOLD")
            px = close_panel[name].get(dt)
            if pd.isna(px):
                continue
            if sig in ("SELL", "AVOID"):
                fill = float(px) * (1 - slip)
                shares = positions[name]["shares"]
                cash += shares * fill
                trades.append(
                    {
                        "date": str(pd.Timestamp(dt).date()),
                        "ticker": name,
                        "side": "SELL",
                        "shares": shares,
                        "price": round(fill, 4),
                        "signal": sig,
                    }
                )
                del positions[name]

        # Entries
        marks = {n: float(close_panel[n].get(dt)) for n in close_panel if not pd.isna(close_panel[n].get(dt))}
        eq = cash + sum(positions[n]["shares"] * marks.get(n, positions[n]["avg_price"]) for n in positions)
        open_count = len(positions)
        buy_candidates = [
            n
            for n in histories
            if n not in positions and signal_panel[n].get(dt) == "BUY" and n in marks
        ]
        # Prefer higher static composite then upside
        buy_candidates.sort(
            key=lambda n: (
                eligibility.get(n, {}).get("composite") or 0,
                eligibility.get(n, {}).get("upside_pct") or 0,
            ),
            reverse=True,
        )
        for name in buy_candidates:
            if open_count >= cfg.max_open_positions:
                break
            px = marks[name]
            fill = px * (1 + slip)
            budget = eq * cfg.max_position_pct
            shares = int(budget // fill)
            if shares <= 0 or shares * fill > cash:
                continue
            cash -= shares * fill
            positions[name] = {"shares": shares, "avg_price": round(fill, 4)}
            trades.append(
                {
                    "date": str(pd.Timestamp(dt).date()),
                    "ticker": name,
                    "side": "BUY",
                    "shares": shares,
                    "price": round(fill, 4),
                    "signal": "BUY",
                }
            )
            open_count += 1
            eq = cash + sum(positions[n]["shares"] * marks.get(n, positions[n]["avg_price"]) for n in positions)

        marks = {n: float(close_panel[n].get(dt)) for n in close_panel if not pd.isna(close_panel[n].get(dt))}
        eq = cash + sum(positions[n]["shares"] * marks.get(n, positions[n]["avg_price"]) for n in positions)
        equity_rows.append(
            {
                "Date": pd.Timestamp(dt),
                "equity": round(eq, 2),
                "cash": round(cash, 2),
                "positions": len(positions),
            }
        )

    eq_df = pd.DataFrame(equity_rows)
    if eq_df.empty:
        result.summary = {"ok": False, "error": "Empty equity curve"}
        return result

    # Buy-and-hold benchmark: equal weight of tradeable names
    bh_start = {n: float(close_panel[n].iloc[0]) for n in close_panel}
    n_names = max(len(bh_start), 1)
    alloc = cfg.starting_cash / n_names
    bh_shares = {n: alloc / px for n, px in bh_start.items() if px > 0}
    bh_curve = []
    for dt in all_dates:
        val = sum(bh_shares[n] * float(close_panel[n].get(dt, bh_start[n])) for n in bh_shares)
        bh_curve.append(val)
    eq_df["buy_hold"] = bh_curve

    start_eq = float(eq_df["equity"].iloc[0])
    end_eq = float(eq_df["equity"].iloc[-1])
    days = max((eq_df["Date"].iloc[-1] - eq_df["Date"].iloc[0]).days, 1)
    years = days / 365.25
    cagr = (end_eq / start_eq) ** (1 / years) - 1 if years > 0 and start_eq > 0 else 0
    roll_max = eq_df["equity"].cummax()
    dd = (eq_df["equity"] / roll_max - 1.0) * 100.0
    max_dd = float(dd.min()) if len(dd) else 0.0
    rets = eq_df["equity"].pct_change().dropna()
    sharpe = float((rets.mean() / rets.std()) * (252**0.5)) if len(rets) > 2 and rets.std() > 0 else 0.0
    bh_end = float(eq_df["buy_hold"].iloc[-1])
    bh_cagr = (bh_end / cfg.starting_cash) ** (1 / years) - 1 if years > 0 else 0

    wins = 0
    closed = 0
    # rough round-trip PnL by pairing
    open_px: dict[str, list] = {}
    for tr in trades:
        t = tr["ticker"]
        if tr["side"] == "BUY":
            open_px.setdefault(t, []).append(tr)
        elif tr["side"] == "SELL" and open_px.get(t):
            buy = open_px[t].pop(0)
            pnl = (tr["price"] - buy["price"]) / buy["price"]
            closed += 1
            if pnl > 0:
                wins += 1

    result.equity_curve = eq_df
    result.trades = trades
    result.summary = {
        "ok": True,
        "start": str(eq_df["Date"].iloc[0].date()),
        "end": str(eq_df["Date"].iloc[-1].date()),
        "starting_cash": cfg.starting_cash,
        "ending_equity": round(end_eq, 2),
        "total_return_pct": round((end_eq / start_eq - 1) * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_approx": round(sharpe, 2),
        "trades": len(trades),
        "round_trips": closed,
        "win_rate_pct": round(100.0 * wins / closed, 1) if closed else None,
        "buy_hold_ending": round(bh_end, 2),
        "buy_hold_cagr_pct": round(bh_cagr * 100, 2),
        "buy_hold_return_pct": round((bh_end / cfg.starting_cash - 1) * 100, 2),
        "tickers_traded": sorted(histories.keys()),
        "tickers_skipped": [k for k, v in result.per_ticker.items() if v.get("skipped")],
        "fundamentals_mode": cfg.fundamentals_mode,
        "sma_period": sma_period,
        "generated": date.today().isoformat(),
    }
    return result


def save_backtest(result: BacktestResult, tag: str = "latest") -> Path:
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    base = BACKTEST_DIR / f"backtest-{tag}-{stamp}"
    summary_path = Path(str(base) + "-summary.json")
    trades_path = Path(str(base) + "-trades.json")
    equity_path = Path(str(base) + "-equity.csv")
    latest_summary = BACKTEST_DIR / "latest-summary.json"
    latest_equity = BACKTEST_DIR / "latest-equity.csv"

    payload = {"summary": result.summary, "per_ticker": result.per_ticker, "notes": result.notes}
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    latest_summary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    trades_path.write_text(json.dumps(result.trades, indent=2), encoding="utf-8")
    if not result.equity_curve.empty:
        result.equity_curve.to_csv(equity_path, index=False)
        result.equity_curve.to_csv(latest_equity, index=False)
    return summary_path
