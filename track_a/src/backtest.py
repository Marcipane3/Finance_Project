"""
Rolling backtest engine for Track A.

Runs both A1 (full rebalance) and A2 (buy-only capital deployment) strategies
in parallel over the configured backtest period (default 2021-01-01 to today).

Usage:
    results = run_backtest("quarterly", mu0_annual=0.10, config=cfg)
    # returns DataFrame: one row per rebalance period
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import yaml

from track_a.src.fscore import filter_by_fscore
from track_a.src.fundamentals import fetch_fundamentals
from track_a.src.optimizer import OptimizeResult, solve_a1, solve_a2
from track_a.src.returns import estimate_mvn, fetch_prices, simulate_scenarios

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config.yaml"


# ── public API ────────────────────────────────────────────────────────────────

@dataclass
class PeriodRecord:
    date: pd.Timestamp
    next_date: pd.Timestamp
    a1_weights: dict                  # {ticker: weight}
    a2_new_weights: dict              # {ticker: weight} — new positions added this period
    a2_cumulative_weights: dict       # {ticker: weight} — full A2 portfolio (growing)
    a1_gross_return: float            # before TC
    a1_net_return: float              # after TC
    a2_net_return: float              # combined (existing + new) after TC
    nav_a1: float
    nav_a2: float
    n_eligible: int
    effective_threshold: int
    a1_status: str
    a2_status: str
    solve_time_a1: float
    solve_time_a2: float


def run_backtest(
    cadence: str,
    mu0_annual: float,
    config: dict,
    initial_nav: float | None = None,
    new_capital_per_period: float | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Roll the portfolio over the backtest window; return a DataFrame of PeriodRecords.

    Parameters
    ----------
    cadence              : "quarterly" or "yearly"
    mu0_annual           : annualized minimum expected return (e.g. 0.10 = 10%)
    config               : parsed config.yaml
    initial_nav          : starting capital in EUR (overrides config if provided)
    new_capital_per_period: new money added each period in EUR (overrides config if provided)
    """
    a_cfg = config["track_a"]
    capital   = initial_nav               if initial_nav               is not None else float(a_cfg["initial_capital_eur"])
    new_cap   = new_capital_per_period    if new_capital_per_period    is not None else float(a_cfg["new_capital_per_period_eur"])
    opt_cfg   = a_cfg["optimizer"]
    ret_cfg   = a_cfg["returns"]
    fs_cfg    = a_cfg["fscore"]

    backtest_start = pd.Timestamp(a_cfg["backtest_start"])
    price_start    = a_cfg["price_history_start"]
    rebal_dates    = _rebal_schedule(cadence, backtest_start)

    logger.info("Backtest: %s cadence, μ₀=%.0f%%, %d periods, capital €%.0f + €%.0f/period",
                cadence, mu0_annual * 100, len(rebal_dates) - 1, capital, new_cap)

    # ── load S&P 500 universe ─────────────────────────────────────────────────
    sp500_tickers = _load_sp500_tickers()
    logger.info("Backtest: %d S&P 500 tickers", len(sp500_tickers))

    # ── fetch prices (2016–present) ───────────────────────────────────────────
    closes = fetch_prices(sp500_tickers, start_date=price_start, force_refresh=force_refresh)
    logger.info("Backtest: prices loaded (%d × %d)", len(closes.columns), len(closes))

    # ── fetch benchmark (SPY) ─────────────────────────────────────────────────
    spy_closes = _load_spy(price_start)

    # ── fetch fundamentals (all tickers, once) ────────────────────────────────
    all_stmts = fetch_fundamentals(sp500_tickers, force_refresh=force_refresh)
    logger.info("Backtest: fundamentals cached for %d tickers", len(all_stmts))

    # ── rolling loop ──────────────────────────────────────────────────────────
    nav_a1 = capital
    nav_a2 = capital
    a1_prev_weights: dict[str, float] = {}    # {ticker: weight} from last A1 rebalance
    a2_cumulative:   dict[str, float] = {}    # {ticker: abs_value_eur} — A2 buy-only holdings

    records: list[PeriodRecord] = []

    for i in range(len(rebal_dates) - 1):
        t     = rebal_dates[i]
        t_end = rebal_dates[i + 1]
        horizon_days = _trading_days_between(closes, t, t_end)
        mu0_h = _scale_mu0(mu0_annual, cadence)

        logger.info("Period %d/%d: %s → %s (%d trading days)",
                    i + 1, len(rebal_dates) - 1, t.date(), t_end.date(), horizon_days)

        # ── F-Score filter ────────────────────────────────────────────────────
        eligible_df = filter_by_fscore(
            sp500_tickers, all_stmts, as_of_date=t,
            threshold=fs_cfg["threshold"], min_count=fs_cfg["min_stocks"],
        )
        eligible = eligible_df["ticker"].tolist()
        eff_thresh = int(eligible_df["effective_threshold"].iloc[0]) if len(eligible_df) else fs_cfg["threshold"]
        logger.info("F-Score filter: %d eligible tickers (threshold=%d)", len(eligible), eff_thresh)

        avail = [t_ for t_ in eligible if t_ in closes.columns]
        if len(avail) < opt_cfg["k_min"]:
            logger.warning("Period %s: only %d price-available tickers, skipping", t.date(), len(avail))
            records.append(_skip_record(t, t_end, nav_a1, nav_a2, len(eligible), eff_thresh,
                                         closes, spy_closes))
            nav_a1 += new_cap
            nav_a2 += new_cap
            continue

        # ── MVN estimation + simulation ───────────────────────────────────────
        mu, sigma = estimate_mvn(closes, avail, as_of_date=t,
                                  lookback_days=ret_cfg["lookback_days"])
        seed = int(t.timestamp()) % (2 ** 31)
        scenarios = simulate_scenarios(mu, sigma, horizon_days=horizon_days,
                                        n_sims=ret_cfg["n_simulations"], seed=seed)
        # scenarios shape: (n_sims × len(avail))

        ticker_idx = {t_: i for i, t_ in enumerate(avail)}

        # ── A1: full rebalance ────────────────────────────────────────────────
        n = len(avail)
        prev_w_vec = np.array([a1_prev_weights.get(t_, 0.0) for t_ in avail])
        new_cap_frac = new_cap / (nav_a1 + new_cap)

        a1_result = solve_a1(
            scenarios=scenarios,
            tickers=avail,
            prev_weights=prev_w_vec,
            new_capital_frac=new_cap_frac,
            mu0=mu0_h,
            beta=opt_cfg["beta"],
            k_min=opt_cfg["k_min"],
            k_max=opt_cfg["k_max"],
            w_min=opt_cfg["w_min"],
            w_max=opt_cfg["w_max"],
            tc_variable=opt_cfg["tc_variable"],
            time_limit_s=opt_cfg["solver_time_limit_s"],
        )

        if a1_result.status == "optimal":
            a1_weights_new = {avail[j]: float(a1_result.weights[j])
                               for j in range(n) if a1_result.weights[j] > 1e-4}
        else:
            a1_weights_new = a1_prev_weights.copy()

        # ── A2: buy-only capital deployment ───────────────────────────────────
        # Existing A2 positions (normalized weights in combined portfolio)
        a2_total_nav = nav_a2 + new_cap
        a2_existing_w = {t_: v / a2_total_nav for t_, v in a2_cumulative.items()
                         if t_ in ticker_idx}
        a2_new_candidates = [t_ for t_ in avail if t_ not in a2_cumulative]

        if a2_new_candidates and new_cap > 0:
            new_cap_frac_a2 = new_cap / a2_total_nav
            existing_ret = _existing_weighted_returns(scenarios, avail, a2_existing_w)
            new_idx = [ticker_idx[t_] for t_ in a2_new_candidates]
            new_scen = scenarios[:, new_idx]

            a2_result = solve_a2(
                new_scenarios=new_scen,
                new_tickers=a2_new_candidates,
                existing_weighted_returns=existing_ret,
                new_capital_frac=new_cap_frac_a2,
                mu0=mu0_h,
                beta=opt_cfg["beta"],
                k_min_new=a_cfg["a2"]["k_min_new"],
                k_max_new=a_cfg["a2"]["k_max_new"],
                w_min_new=opt_cfg["w_min"],
                w_max_new=opt_cfg["w_max"],
                time_limit_s=opt_cfg["solver_time_limit_s"],
            )
            a2_new_w = {a2_new_candidates[j]: float(a2_result.weights[j])
                         for j in range(len(a2_new_candidates))
                         if a2_result.weights[j] > 1e-4}
        else:
            a2_result = OptimizeResult(np.zeros(0), 0.0, 0.0, 0.0, 0, "skipped", 0.0)
            a2_new_w = {}

        # ── compute realized holding-period returns ────────────────────────────
        a1_gross, a1_net = _realized_return(
            a1_weights_new, closes, t, t_end,
            n_new_positions=len(set(a1_weights_new) - set(a1_prev_weights)),
            nav=nav_a1 + new_cap,
            fixed_fee_eur=_fixed_fee_eur(config),
        )
        a2_net = _realized_return_a2(
            a2_existing_w, a2_new_w, closes, t, t_end,
            n_new=len(a2_new_w),
            nav=a2_total_nav,
            fixed_fee_eur=_fixed_fee_eur(config),
        )

        # ── update state ──────────────────────────────────────────────────────
        nav_a1 = (nav_a1 + new_cap) * (1 + a1_net)
        nav_a2 = a2_total_nav * (1 + a2_net)
        a1_prev_weights = a1_weights_new
        # Update A2 cumulative with new positions (at their new weights × nav_a2)
        for t_, w in a2_new_w.items():
            a2_cumulative[t_] = w * a2_total_nav
        # Mark-to-market existing A2 holdings
        a2_cumulative = _mark_to_market_a2(a2_cumulative, closes, t, t_end)

        records.append(PeriodRecord(
            date=t, next_date=t_end,
            a1_weights=a1_weights_new,
            a2_new_weights=a2_new_w,
            a2_cumulative_weights={t_: v / nav_a2 for t_, v in a2_cumulative.items()},
            a1_gross_return=a1_gross,
            a1_net_return=a1_net,
            a2_net_return=a2_net,
            nav_a1=nav_a1,
            nav_a2=nav_a2,
            n_eligible=len(eligible),
            effective_threshold=eff_thresh,
            a1_status=a1_result.status,
            a2_status=a2_result.status,
            solve_time_a1=a1_result.solve_time_s,
            solve_time_a2=a2_result.solve_time_s,
        ))
        logger.info("Period end: A1 nav=€%.0f (%.1f%%), A2 nav=€%.0f (%.1f%%)",
                    nav_a1, a1_net * 100, nav_a2, a2_net * 100)

    df = pd.DataFrame([
        {
            "date": r.date, "next_date": r.next_date,
            "a1_return_net": r.a1_net_return, "a1_return_gross": r.a1_gross_return,
            "a2_return_net": r.a2_net_return,
            "nav_a1": r.nav_a1, "nav_a2": r.nav_a2,
            "n_eligible": r.n_eligible, "effective_threshold": r.effective_threshold,
            "a1_status": r.a1_status, "a2_status": r.a2_status,
            "n_a1_positions": len(r.a1_weights), "n_a2_new": len(r.a2_new_weights),
            "solve_time_a1": r.solve_time_a1, "solve_time_a2": r.solve_time_a2,
            "a1_weights": r.a1_weights, "a2_cumulative_weights": r.a2_cumulative_weights,
        }
        for r in records
    ])
    return df


# ── rebalance schedule ────────────────────────────────────────────────────────

def _rebal_schedule(cadence: str, start: pd.Timestamp) -> list[pd.Timestamp]:
    today = pd.Timestamp(date.today())
    dates: list[pd.Timestamp] = []
    if cadence == "quarterly":
        # Last trading day of each quarter-end month (March, June, Sept, Dec)
        quarter_ends = pd.date_range(start, today, freq="QE")
        dates = [_last_bday(d) for d in quarter_ends]
    elif cadence == "yearly":
        year_ends = pd.date_range(start, today, freq="YE")
        dates = [_last_bday(d) for d in year_ends]
    else:
        raise ValueError(f"Unknown cadence: {cadence!r}")
    # Include today as the final "next date" for the last period
    if not dates or dates[-1] < today - pd.Timedelta(days=30):
        dates.append(today)
    return dates


def _last_bday(d: pd.Timestamp) -> pd.Timestamp:
    if d.dayofweek == 5:    # Saturday
        return d - pd.Timedelta(days=1)
    if d.dayofweek == 6:    # Sunday
        return d - pd.Timedelta(days=2)
    return d


def _scale_mu0(mu0_annual: float, cadence: str) -> float:
    if cadence == "quarterly":
        return (1 + mu0_annual) ** 0.25 - 1
    return mu0_annual


def _trading_days_between(closes: pd.DataFrame, t_start: pd.Timestamp, t_end: pd.Timestamp) -> int:
    if closes.empty or not isinstance(closes.index, pd.DatetimeIndex):
        return 63   # fallback quarter
    mask = (closes.index > t_start) & (closes.index <= t_end)
    n = int(mask.sum())
    return n if n > 0 else 63   # fallback quarter


# ── data helpers ──────────────────────────────────────────────────────────────

def _load_sp500_tickers() -> list[str]:
    from track_b.src.universe import _scrape_sp500  # type: ignore[import-untyped]
    try:
        df = _scrape_sp500()
        return df["ticker"].tolist()
    except Exception as exc:
        logger.warning("S&P 500 scrape failed (%s), using cached if available", exc)
        cache = Path(__file__).parent.parent.parent / "track_b" / "data" / "cache" / "universe.parquet"
        if cache.exists():
            df = pd.read_parquet(cache)
            sp500 = df[df.get("index", pd.Series(dtype=str)) == "sp500"] if "index" in df.columns else df
            return sp500["ticker"].tolist()
        return []


def _load_spy(start_date: str) -> pd.Series:
    try:
        raw = yf.download("SPY", start=start_date, auto_adjust=True, progress=False)
        close = raw["Close"] if "Close" in raw.columns else raw.iloc[:, 0]
        return close.squeeze()
    except Exception:
        return pd.Series(dtype=float)


def _fixed_fee_eur(config: dict) -> float:
    fees = config.get("fees", {})
    dkk_per_trade = float(fees.get("fixed_dkk_per_trade", 29.0))
    dkk_per_eur   = float(fees.get("dkk_per_eur", 7.46))
    return dkk_per_trade / dkk_per_eur


# ── return calculation ────────────────────────────────────────────────────────

def _realized_return(
    weights: dict[str, float],
    closes: pd.DataFrame,
    t_start: pd.Timestamp,
    t_end: pd.Timestamp,
    n_new_positions: int,
    nav: float,
    fixed_fee_eur: float,
) -> tuple[float, float]:
    """Compute gross and net realized return for an A1 portfolio over the holding period."""
    if not weights:
        return 0.0, 0.0
    total = 0.0
    for ticker, w in weights.items():
        r = _ticker_return(closes, ticker, t_start, t_end)
        total += w * r
    gross = total
    tc_fixed = n_new_positions * fixed_fee_eur / nav if nav > 0 else 0.0
    return gross, gross - tc_fixed


def _realized_return_a2(
    existing_w: dict[str, float],
    new_w: dict[str, float],
    closes: pd.DataFrame,
    t_start: pd.Timestamp,
    t_end: pd.Timestamp,
    n_new: int,
    nav: float,
    fixed_fee_eur: float,
) -> float:
    """Net return for A2 combined portfolio (existing fixed + new positions)."""
    total = 0.0
    for ticker, w in {**existing_w, **new_w}.items():
        total += w * _ticker_return(closes, ticker, t_start, t_end)
    tc_fixed = n_new * fixed_fee_eur / nav if nav > 0 else 0.0
    return total - tc_fixed


def _ticker_return(
    closes: pd.DataFrame,
    ticker: str,
    t_start: pd.Timestamp,
    t_end: pd.Timestamp,
) -> float:
    if ticker not in closes.columns:
        return 0.0
    series = closes[ticker].dropna()
    start_row = series[series.index <= t_start]
    end_row   = series[series.index <= t_end]
    if start_row.empty or end_row.empty:
        return 0.0
    p0 = float(start_row.iloc[-1])
    p1 = float(end_row.iloc[-1])
    return (p1 - p0) / p0 if p0 > 0 else 0.0


def _existing_weighted_returns(
    scenarios: np.ndarray,
    avail: list[str],
    existing_w: dict[str, float],
) -> np.ndarray:
    """Compute (S,) vector = Σ_i w_i * r_i for tickers already in A2 portfolio."""
    ticker_idx = {t: i for i, t in enumerate(avail)}
    S = scenarios.shape[0]
    result = np.zeros(S)
    for t, w in existing_w.items():
        if t in ticker_idx:
            result += w * scenarios[:, ticker_idx[t]]
    return result


def _mark_to_market_a2(
    holdings: dict[str, float],   # {ticker: abs_value_eur}
    closes: pd.DataFrame,
    t_start: pd.Timestamp,
    t_end: pd.Timestamp,
) -> dict[str, float]:
    """Update absolute holding values with realized returns over the period."""
    updated = {}
    for ticker, value in holdings.items():
        r = _ticker_return(closes, ticker, t_start, t_end)
        updated[ticker] = value * (1 + r)
    return updated


# ── skip record (when filter yields too few tickers) ─────────────────────────

def _skip_record(
    t: pd.Timestamp,
    t_end: pd.Timestamp,
    nav_a1: float,
    nav_a2: float,
    n_eligible: int,
    eff_thresh: int,
    closes: pd.DataFrame,
    spy_closes: pd.Series,
) -> PeriodRecord:
    return PeriodRecord(
        date=t, next_date=t_end,
        a1_weights={}, a2_new_weights={}, a2_cumulative_weights={},
        a1_gross_return=0.0, a1_net_return=0.0, a2_net_return=0.0,
        nav_a1=nav_a1, nav_a2=nav_a2,
        n_eligible=n_eligible, effective_threshold=eff_thresh,
        a1_status="skipped", a2_status="skipped",
        solve_time_a1=0.0, solve_time_a2=0.0,
    )
