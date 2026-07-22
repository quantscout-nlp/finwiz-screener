"""Monte Carlo + in-sample / out-of-sample metrics on Finwiz equity curves."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from lib_backtest import BACKTEST_DIR, BacktestConfig, BacktestResult, run_backtest, save_backtest
from lib_finwiz import load_toggles
from lib_market_data import provider_status, years_ago_iso


def _metrics_from_equity(equity: pd.Series, starting_cash: float | None = None) -> dict[str, float]:
    eq = equity.dropna().astype(float)
    if len(eq) < 5:
        return {"cagr_pct": 0.0, "max_drawdown_pct": 0.0, "sharpe": 0.0, "total_return_pct": 0.0}
    start = float(starting_cash if starting_cash is not None else eq.iloc[0])
    end = float(eq.iloc[-1])
    # approximate years from length of daily series
    years = max(len(eq) / 252.0, 1 / 252.0)
    cagr = (end / start) ** (1 / years) - 1 if start > 0 else 0.0
    roll_max = eq.cummax()
    dd = (eq / roll_max - 1.0) * 100.0
    max_dd = float(dd.min())
    rets = eq.pct_change().dropna()
    sharpe = float((rets.mean() / rets.std()) * np.sqrt(252)) if len(rets) > 2 and rets.std() > 0 else 0.0
    return {
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe": round(sharpe, 2),
        "total_return_pct": round((end / start - 1) * 100, 2),
        "ending_equity": round(end, 2),
    }


def split_is_oos(result: BacktestResult, oos_ratio: float = 0.3) -> dict[str, Any]:
    eq = result.equity_curve
    if eq is None or eq.empty or "equity" not in eq.columns:
        return {"ok": False, "error": "missing equity curve"}
    n = len(eq)
    cut = max(int(n * (1 - oos_ratio)), 50)
    cut = min(cut, n - 20) if n > 70 else n // 2
    is_eq = eq["equity"].iloc[:cut]
    oos_eq = eq["equity"].iloc[cut - 1 :]  # overlap 1 day for continuity of start
    # rebase OOS to continue from IS end conceptually — report standalone OOS path from cut
    oos_path = eq["equity"].iloc[cut:].reset_index(drop=True)
    is_m = _metrics_from_equity(is_eq)
    oos_m = _metrics_from_equity(oos_path, starting_cash=float(eq["equity"].iloc[cut]))
    full_m = _metrics_from_equity(eq["equity"])
    return {
        "ok": True,
        "is_bars": int(len(is_eq)),
        "oos_bars": int(len(oos_path)),
        "is_end_date": str(pd.Timestamp(eq["Date"].iloc[cut - 1]).date()) if "Date" in eq.columns else None,
        "oos_start_date": str(pd.Timestamp(eq["Date"].iloc[cut]).date()) if "Date" in eq.columns else None,
        "full": full_m,
        "in_sample": is_m,
        "out_of_sample": oos_m,
        "buy_hold_full": _metrics_from_equity(eq["buy_hold"]) if "buy_hold" in eq.columns else None,
    }


def monte_carlo_from_equity(
    equity: pd.Series,
    n_sims: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """Bootstrap daily returns to simulate alternate equity paths."""
    eq = equity.dropna().astype(float)
    rets = eq.pct_change().dropna().values
    if len(rets) < 30:
        return {"ok": False, "error": "insufficient returns for Monte Carlo"}
    rng = np.random.default_rng(seed)
    start = float(eq.iloc[0])
    cagrs, sharpes, maxdds, totals = [], [], [], []
    for _ in range(n_sims):
        boot = rng.choice(rets, size=len(rets), replace=True)
        path = start * np.cumprod(1.0 + boot)
        path = np.insert(path, 0, start)
        s = pd.Series(path)
        m = _metrics_from_equity(s, starting_cash=start)
        cagrs.append(m["cagr_pct"])
        sharpes.append(m["sharpe"])
        maxdds.append(m["max_drawdown_pct"])
        totals.append(m["total_return_pct"])

    def pct(arr: list[float], p: float) -> float:
        return round(float(np.percentile(arr, p)), 2)

    return {
        "ok": True,
        "n_sims": n_sims,
        "cagr_pct": {"p5": pct(cagrs, 5), "p50": pct(cagrs, 50), "p95": pct(cagrs, 95), "mean": round(float(np.mean(cagrs)), 2)},
        "sharpe": {"p5": pct(sharpes, 5), "p50": pct(sharpes, 50), "p95": pct(sharpes, 95), "mean": round(float(np.mean(sharpes)), 2)},
        "max_drawdown_pct": {
            "p5": pct(maxdds, 5),
            "p50": pct(maxdds, 50),
            "p95": pct(maxdds, 95),
            "mean": round(float(np.mean(maxdds)), 2),
        },
        "total_return_pct": {
            "p5": pct(totals, 5),
            "p50": pct(totals, 50),
            "p95": pct(totals, 95),
            "mean": round(float(np.mean(totals)), 2),
        },
    }


@dataclass
class AdvancedBacktestConfig:
    years: float = 10.0
    oos_ratio: float = 0.3
    mc_sims: int = 1000
    mc_seed: int = 42
    price_provider: str = "auto"
    fundamentals_mode: str = "pit"  # pit | static | technicals_only
    starting_cash: float = 100_000.0
    max_open_positions: int = 5
    max_position_pct: float = 0.10
    sma_period: int | None = None
    bar_resolution: str = "Day"

def run_advanced_backtest(
    tickers: list[str] | None = None,
    cfg: AdvancedBacktestConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or AdvancedBacktestConfig()
    toggles = load_toggles()
    if cfg.sma_period is not None:
        toggles.setdefault("sma_filter", {})["period"] = int(cfg.sma_period)
        toggles["sma_filter"]["enabled"] = True

    start = years_ago_iso(cfg.years)
    bt_cfg = BacktestConfig(
        start=start,
        starting_cash=cfg.starting_cash,
        max_open_positions=cfg.max_open_positions,
        max_position_pct=cfg.max_position_pct,
        fundamentals_mode=cfg.fundamentals_mode,
        price_provider=cfg.price_provider,
        bar_resolution=cfg.bar_resolution,
    )
    result = run_backtest(tickers=tickers, cfg=bt_cfg, toggles=toggles)
    save_backtest(result, tag=f"adv-{int(cfg.years)}y")

    is_oos = split_is_oos(result, oos_ratio=cfg.oos_ratio)
    mc = {"ok": False, "error": "no equity"}
    if result.equity_curve is not None and not result.equity_curve.empty:
        mc = monte_carlo_from_equity(result.equity_curve["equity"], n_sims=cfg.mc_sims, seed=cfg.mc_seed)

    report = {
        "ok": bool(result.summary.get("ok")),
        "generated": date.today().isoformat(),
        "providers_configured": provider_status(),
        "config": {
            "years": cfg.years,
            "start": start,
            "oos_ratio": cfg.oos_ratio,
            "mc_sims": cfg.mc_sims,
            "price_provider": cfg.price_provider,
            "fundamentals_mode": cfg.fundamentals_mode,
            "sma_period": toggles.get("sma_filter", {}).get("period"),
        },
        "base_summary": result.summary,
        "is_oos": is_oos,
        "monte_carlo": mc,
        "notes": result.notes
        + [
            "IS = first (1-oos_ratio) of equity path; OOS = remaining path.",
            "Monte Carlo bootstraps daily strategy returns (paths are scrambled — stress test, not forecast).",
            "Price providers: Massive → Alpaca (IEX/SIP) → Tiingo → yfinance.",
            "Benzinga/Massive ratings & news enrich research; signal timing still uses Finwiz BUY/HOLD rules.",
        ],
        "per_ticker": result.per_ticker,
    }

    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    out = BACKTEST_DIR / "advanced-latest.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
