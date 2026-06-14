"""
Piotroski F-Score computation for Track A.

Implements all 9 binary signals from Piotroski (2000).  Each signal returns 1 if
the condition is met, 0 otherwise. Score = sum of 9 signals (0–9).

Look-ahead-bias guard: only fiscal years where fiscal_year_end + 90 days ≤ as_of_date
are used. Annual data (10-K) only — no TTM aggregation from quarterly filings.

Public API:
    compute_fscore(statements, as_of_date) -> (score: int, signals: dict)
    compute_all_fscores(tickers, all_statements, as_of_date) -> DataFrame
    filter_by_fscore(tickers, all_statements, as_of_date,
                     threshold=8, min_count=10) -> DataFrame
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── public API ────────────────────────────────────────────────────────────────

def compute_fscore(
    statements: dict[str, pd.DataFrame],
    as_of_date: pd.Timestamp,
    filing_lag_days: int = 90,
) -> tuple[int, dict]:
    """Compute F-Score for a single ticker.

    Parameters
    ----------
    statements : dict with keys "balance_sheet", "income_stmt", "cashflow"
                 Each is a DataFrame with fiscal year Timestamps as columns.
    as_of_date : Only use fiscal years filed by this date (fiscal_year_end + lag ≤ as_of_date).
    filing_lag_days : Conservative filing lag (default 90 days after fiscal year-end).

    Returns
    -------
    (score, signals_dict) where signals_dict maps signal name → 0 or 1 (or None if data missing).
    """
    bs  = statements.get("balance_sheet",  pd.DataFrame())
    inc = statements.get("income_stmt",    pd.DataFrame())
    cf  = statements.get("cashflow",       pd.DataFrame())

    # Find the two most recent fiscal years available as of as_of_date
    t_col, t1_col = _select_years(bs, as_of_date, filing_lag_days)
    if t_col is None:
        return 0, {s: None for s in _SIGNAL_NAMES}

    signals = {}

    # ── Profitability ─────────────────────────────────────────────────────────
    net_income_t  = _get(inc, "Net Income",         t_col)
    total_assets_t = _get(bs, "Total Assets",        t_col)
    total_assets_t1 = _get(bs, "Total Assets",       t1_col)
    ocf_t         = _get(cf,  "Operating Cash Flow", t_col)
    net_income_t1 = _get(inc, "Net Income",          t1_col)

    avg_assets = _mean(total_assets_t, total_assets_t1)
    roa_t  = _safe_div(net_income_t,  total_assets_t)
    roa_t1 = _safe_div(net_income_t1, total_assets_t1)

    signals["F1_roa_positive"]    = _binary(roa_t is not None and roa_t > 0)
    signals["F2_ocf_positive"]    = _binary(ocf_t is not None and ocf_t > 0)
    signals["F3_delta_roa"]       = _binary(
        roa_t is not None and roa_t1 is not None and roa_t > roa_t1
    )
    # F4: accruals — OCF/assets > ROA means cash earnings > accounting earnings
    ocf_over_assets = _safe_div(ocf_t, total_assets_t)
    signals["F4_accruals"]        = _binary(
        ocf_over_assets is not None and roa_t is not None and ocf_over_assets > roa_t
    )

    # ── Leverage / Liquidity / Funding ────────────────────────────────────────
    lt_debt_t  = _get_first(bs, ["Long Term Debt", "Long-Term Debt",
                                  "Long Term Debt And Capital Lease Obligation"], t_col,  default=0.0)
    lt_debt_t1 = _get_first(bs, ["Long Term Debt", "Long-Term Debt",
                                  "Long Term Debt And Capital Lease Obligation"], t1_col, default=0.0)
    curr_assets_t  = _get(bs, "Current Assets",      t_col)
    curr_assets_t1 = _get(bs, "Current Assets",      t1_col)
    curr_liab_t    = _get(bs, "Current Liabilities", t_col)
    curr_liab_t1   = _get(bs, "Current Liabilities", t1_col)
    shares_t       = _get_first(bs, ["Ordinary Shares Number", "Common Stock",
                                      "Share Issued"], t_col)
    shares_t1      = _get_first(bs, ["Ordinary Shares Number", "Common Stock",
                                      "Share Issued"], t1_col)

    lev_t  = _safe_div(lt_debt_t,  avg_assets)
    lev_t1 = _safe_div(lt_debt_t1, _get(bs, "Total Assets", t1_col))  # prior avg not available

    cr_t  = _safe_div(curr_assets_t,  curr_liab_t)
    cr_t1 = _safe_div(curr_assets_t1, curr_liab_t1)

    signals["F5_delta_leverage"]  = _binary(
        lev_t is not None and lev_t1 is not None and lev_t < lev_t1
    )
    signals["F6_delta_current_ratio"] = _binary(
        cr_t is not None and cr_t1 is not None and cr_t > cr_t1
    )
    signals["F7_no_dilution"]     = _binary(
        shares_t is not None and shares_t1 is not None and shares_t <= shares_t1
    )

    # ── Operating Efficiency ──────────────────────────────────────────────────
    revenue_t  = _get_first(inc, ["Total Revenue", "Revenue"], t_col)
    revenue_t1 = _get_first(inc, ["Total Revenue", "Revenue"], t1_col)
    gross_t    = _get_first(inc, ["Gross Profit", "Gross Income"], t_col)
    gross_t1   = _get_first(inc, ["Gross Profit", "Gross Income"], t1_col)

    gm_t  = _safe_div(gross_t,  revenue_t)
    gm_t1 = _safe_div(gross_t1, revenue_t1)
    at_t  = _safe_div(revenue_t,  total_assets_t)
    at_t1 = _safe_div(revenue_t1, total_assets_t1)

    signals["F8_delta_gross_margin"]   = _binary(
        gm_t is not None and gm_t1 is not None and gm_t > gm_t1
    )
    signals["F9_delta_asset_turnover"] = _binary(
        at_t is not None and at_t1 is not None and at_t > at_t1
    )

    valid_signals = [v for v in signals.values() if v is not None]
    score = int(sum(valid_signals))
    return score, signals


def compute_all_fscores(
    tickers: list[str],
    all_statements: dict[str, dict[str, pd.DataFrame]],
    as_of_date: pd.Timestamp,
) -> pd.DataFrame:
    """Compute F-Score for all tickers. Returns DataFrame with columns: ticker, score, + 9 signals."""
    rows = []
    for ticker in tickers:
        stmts = all_statements.get(ticker, {})
        score, signals = compute_fscore(stmts, as_of_date)
        rows.append({"ticker": ticker, "fscore": score, **signals})
    return pd.DataFrame(rows)


def filter_by_fscore(
    tickers: list[str],
    all_statements: dict[str, dict[str, pd.DataFrame]],
    as_of_date: pd.Timestamp,
    threshold: int = 8,
    min_count: int = 10,
) -> pd.DataFrame:
    """Return tickers passing F-Score threshold. Lowers threshold in steps until min_count met.

    Returns DataFrame with columns: ticker, fscore, effective_threshold, + 9 signals.
    """
    scores_df = compute_all_fscores(tickers, all_statements, as_of_date)
    effective_threshold = threshold

    for t in range(threshold, -1, -1):
        passing = scores_df[scores_df["fscore"] >= t]
        if len(passing) >= min_count:
            effective_threshold = t
            if t < threshold:
                logger.warning(
                    "F-Score filter: threshold lowered %d→%d at %s (%d stocks passed at %d)",
                    threshold, t, as_of_date.date(), len(passing), threshold,
                )
            break
    else:
        passing = scores_df
        effective_threshold = 0
        logger.warning("F-Score filter: no threshold yielded %d stocks, returning all %d",
                        min_count, len(passing))

    result = passing.copy()
    result["effective_threshold"] = effective_threshold
    return result.sort_values("fscore", ascending=False).reset_index(drop=True)


# ── helpers ───────────────────────────────────────────────────────────────────

_SIGNAL_NAMES = [
    "F1_roa_positive", "F2_ocf_positive", "F3_delta_roa", "F4_accruals",
    "F5_delta_leverage", "F6_delta_current_ratio", "F7_no_dilution",
    "F8_delta_gross_margin", "F9_delta_asset_turnover",
]


def _select_years(
    df: pd.DataFrame,
    as_of_date: pd.Timestamp,
    lag_days: int,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """Return the two most recent fiscal year columns available as_of_date (with lag applied)."""
    if df.empty or not len(df.columns):
        return None, None

    cutoff = as_of_date - pd.Timedelta(days=lag_days)
    # yfinance columns are period-end Timestamps
    eligible = sorted(
        [c for c in df.columns if pd.notna(c) and pd.Timestamp(c) <= cutoff],
        reverse=True,
    )
    if len(eligible) < 2:
        return None, None
    return pd.Timestamp(eligible[0]), pd.Timestamp(eligible[1])


def _get(df: pd.DataFrame, row: str, col: pd.Timestamp) -> float | None:
    """Safely get df.loc[row, col], returning None if missing or NaN."""
    if df.empty or row not in df.index or col not in df.columns:
        return None
    val = df.loc[row, col]
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _get_first(
    df: pd.DataFrame,
    candidates: list[str],
    col: pd.Timestamp,
    default: float | None = None,
) -> float | None:
    """Try multiple row-name candidates; return first non-None result."""
    for name in candidates:
        val = _get(df, name, col)
        if val is not None:
            return val
    return default


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _mean(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return (a + b) / 2


def _binary(condition: bool) -> int:
    return 1 if condition else 0
