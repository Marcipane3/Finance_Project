"""
Performance metrics for Track A backtest results.

All functions accept a NAV series (pd.Series with date index, absolute EUR values).
"""

import numpy as np
import pandas as pd


def compute_metrics(nav_series: pd.Series, benchmark_nav: pd.Series | None = None) -> dict:
    """Compute standard portfolio performance metrics.

    Parameters
    ----------
    nav_series    : Series of portfolio NAV at each rebalance date (EUR)
    benchmark_nav : Optional Series of benchmark NAV (same dates or broader)

    Returns
    -------
    dict with keys: cagr, annualized_sharpe, max_drawdown, realized_cvar_10,
                    total_return, n_periods, benchmark_cagr (if provided)
    """
    if nav_series.empty or len(nav_series) < 2:
        return {"error": "insufficient data"}

    nav_series = nav_series.sort_index().dropna()
    returns = nav_series.pct_change().dropna()

    cagr     = _cagr(nav_series)
    sharpe   = _annualized_sharpe(returns)
    max_dd   = _max_drawdown(nav_series)
    cvar_10  = _cvar(returns, tail_pct=0.10)
    total_r  = float(nav_series.iloc[-1] / nav_series.iloc[0] - 1)

    result = {
        "cagr":              cagr,
        "annualized_sharpe": sharpe,
        "max_drawdown":      max_dd,
        "realized_cvar_10":  cvar_10,
        "total_return":      total_r,
        "n_periods":         len(returns),
    }

    if benchmark_nav is not None and not benchmark_nav.empty:
        # Align benchmark to portfolio dates
        aligned = benchmark_nav.reindex(nav_series.index, method="ffill").dropna()
        if len(aligned) >= 2:
            result["benchmark_cagr"]         = _cagr(aligned)
            result["benchmark_total_return"] = float(aligned.iloc[-1] / aligned.iloc[0] - 1)
            bmark_ret = aligned.pct_change().dropna()
            if len(bmark_ret) > 1:
                result["benchmark_sharpe"] = _annualized_sharpe(bmark_ret)

    return result


def build_nav_series(backtest_df: pd.DataFrame, column: str = "nav_a1") -> pd.Series:
    """Extract a date-indexed NAV Series from the backtest DataFrame."""
    df = backtest_df[["date", column]].dropna().copy()
    df = df.set_index("date").sort_index()
    return df[column]


def compare_strategies(
    backtest_df: pd.DataFrame,
    benchmark_nav: pd.Series | None = None,
) -> pd.DataFrame:
    """Return a comparison table: A1 vs A2 metrics side by side."""
    a1_nav = build_nav_series(backtest_df, "nav_a1")
    a2_nav = build_nav_series(backtest_df, "nav_a2")

    m_a1 = compute_metrics(a1_nav, benchmark_nav)
    m_a2 = compute_metrics(a2_nav, benchmark_nav)

    rows = []
    for key in ["cagr", "annualized_sharpe", "max_drawdown", "realized_cvar_10", "total_return"]:
        rows.append({
            "metric":    key,
            "A1_rebalance": _fmt(m_a1.get(key)),
            "A2_buy_only":  _fmt(m_a2.get(key)),
            "benchmark":    _fmt(m_a1.get(f"benchmark_{key.split('_')[0]}", m_a1.get("benchmark_cagr") if key == "cagr" else None)),
        })
    return pd.DataFrame(rows)


# ── internal calculations ─────────────────────────────────────────────────────

def _cagr(nav: pd.Series) -> float:
    start, end = nav.index[0], nav.index[-1]
    years = max((end - start).days / 365.25, 1e-6)
    ratio = nav.iloc[-1] / nav.iloc[0]
    return float(ratio ** (1 / years) - 1)


def _annualized_sharpe(returns: pd.Series, risk_free: float = 0.0) -> float:
    if len(returns) < 2 or returns.std() == 0:
        return float("nan")
    # Detect approximate period length from median gap between index dates
    if hasattr(returns.index, "to_series"):
        gaps = returns.index.to_series().diff().dropna()
        median_days = float(gaps.dt.days.median()) if len(gaps) > 0 else 90
    else:
        median_days = 90
    periods_per_year = 365.25 / max(median_days, 1)
    excess = returns - risk_free / periods_per_year
    return float(excess.mean() / excess.std() * np.sqrt(periods_per_year))


def _max_drawdown(nav: pd.Series) -> float:
    peak = nav.cummax()
    dd = (nav - peak) / peak
    return float(dd.min())


def _cvar(returns: pd.Series, tail_pct: float = 0.10) -> float:
    if len(returns) < 2:
        return float("nan")
    threshold = np.quantile(returns, tail_pct)
    tail = returns[returns <= threshold]
    return float(-tail.mean()) if len(tail) > 0 else float("nan")


def _fmt(val) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "—"
    if isinstance(val, float):
        return f"{val:.2%}" if abs(val) < 100 else f"{val:.1f}"
    return str(val)
