"""
Unit tests for track_a.src.fscore.

Uses synthetic DataFrames with known values — no network calls.
"""

import numpy as np
import pandas as pd
import pytest

from track_a.src.fscore import (
    _select_years,
    compute_all_fscores,
    compute_fscore,
    filter_by_fscore,
)

# ── helpers to build synthetic statement DataFrames ──────────────────────────

def _bs(rows: dict, year_t: pd.Timestamp, year_t1: pd.Timestamp) -> pd.DataFrame:
    """Build a balance-sheet-shaped DataFrame with two fiscal year columns."""
    return pd.DataFrame(
        {year_t: {k: v[0] for k, v in rows.items()},
         year_t1: {k: v[1] for k, v in rows.items()}}
    )


def _inc(rows: dict, year_t: pd.Timestamp, year_t1: pd.Timestamp) -> pd.DataFrame:
    return pd.DataFrame(
        {year_t: {k: v[0] for k, v in rows.items()},
         year_t1: {k: v[1] for k, v in rows.items()}}
    )


def _cf(rows: dict, year_t: pd.Timestamp, year_t1: pd.Timestamp) -> pd.DataFrame:
    return pd.DataFrame(
        {year_t: {k: v[0] for k, v in rows.items()},
         year_t1: {k: v[1] for k, v in rows.items()}}
    )


# Fiscal years well before as_of_date so lag guard doesn't reject them
YEAR_T  = pd.Timestamp("2022-12-31")
YEAR_T1 = pd.Timestamp("2021-12-31")
AS_OF   = pd.Timestamp("2023-04-30")   # 90d after 2022-12-31 → eligible


def _baseline_statements(
    *,
    net_income_t=100,   net_income_t1=80,
    total_assets_t=500, total_assets_t1=480,
    ocf_t=120,
    lt_debt_t=50,       lt_debt_t1=60,
    curr_assets_t=200,  curr_assets_t1=180,
    curr_liab_t=100,    curr_liab_t1=100,
    shares_t=100,       shares_t1=100,
    revenue_t=400,      revenue_t1=360,
    gross_t=160,        gross_t1=130,
) -> dict[str, pd.DataFrame]:
    bs = _bs({
        "Total Assets":      (total_assets_t,  total_assets_t1),
        "Long Term Debt":    (lt_debt_t,        lt_debt_t1),
        "Current Assets":    (curr_assets_t,    curr_assets_t1),
        "Current Liabilities": (curr_liab_t,    curr_liab_t1),
        "Ordinary Shares Number": (shares_t,    shares_t1),
    }, YEAR_T, YEAR_T1)
    inc = _inc({
        "Net Income":    (net_income_t,  net_income_t1),
        "Total Revenue": (revenue_t,     revenue_t1),
        "Gross Profit":  (gross_t,       gross_t1),
    }, YEAR_T, YEAR_T1)
    cf = _cf({
        "Operating Cash Flow": (ocf_t, 0),
    }, YEAR_T, YEAR_T1)
    return {"balance_sheet": bs, "income_stmt": inc, "cashflow": cf}


# ── _select_years ─────────────────────────────────────────────────────────────

def test_select_years_basic():
    bs = _bs({"Total Assets": (500, 480)}, YEAR_T, YEAR_T1)
    t, t1 = _select_years(bs, AS_OF, lag_days=90)
    assert t == YEAR_T
    assert t1 == YEAR_T1


def test_select_years_lag_blocks_recent():
    # as_of is only 30 days after YEAR_T — lag=90 should block it
    as_of_early = pd.Timestamp("2023-01-30")
    bs = _bs({"Total Assets": (500, 480)}, YEAR_T, YEAR_T1)
    t, t1 = _select_years(bs, as_of_early, lag_days=90)
    # YEAR_T (2022-12-31 + 90d = 2023-03-31) > 2023-01-30 → blocked
    # only YEAR_T1 available → not enough for 2 years
    assert t is None


def test_select_years_empty_df():
    t, t1 = _select_years(pd.DataFrame(), AS_OF, 90)
    assert t is None and t1 is None


# ── compute_fscore — all 9 signals individually ───────────────────────────────

def test_f1_roa_positive_pass():
    s = _baseline_statements(net_income_t=100, total_assets_t=500)  # ROA = 0.2 > 0
    _, sig = compute_fscore(s, AS_OF)
    assert sig["F1_roa_positive"] == 1

def test_f1_roa_positive_fail():
    s = _baseline_statements(net_income_t=-50)  # ROA < 0
    _, sig = compute_fscore(s, AS_OF)
    assert sig["F1_roa_positive"] == 0

def test_f2_ocf_positive_pass():
    s = _baseline_statements(ocf_t=120)
    _, sig = compute_fscore(s, AS_OF)
    assert sig["F2_ocf_positive"] == 1

def test_f2_ocf_positive_fail():
    s = _baseline_statements(ocf_t=-10)
    _, sig = compute_fscore(s, AS_OF)
    assert sig["F2_ocf_positive"] == 0

def test_f3_delta_roa_pass():
    # ROA_t = 100/500=0.20, ROA_t1 = 80/480=0.167 → delta > 0
    s = _baseline_statements()
    _, sig = compute_fscore(s, AS_OF)
    assert sig["F3_delta_roa"] == 1

def test_f3_delta_roa_fail():
    # ROA_t = 50/500=0.10, ROA_t1 = 80/480=0.167 → delta < 0
    s = _baseline_statements(net_income_t=50)
    _, sig = compute_fscore(s, AS_OF)
    assert sig["F3_delta_roa"] == 0

def test_f4_accruals_pass():
    # OCF/assets = 120/500=0.24 > ROA = 100/500=0.20 → pass
    s = _baseline_statements()
    _, sig = compute_fscore(s, AS_OF)
    assert sig["F4_accruals"] == 1

def test_f4_accruals_fail():
    # OCF/assets = 20/500=0.04 < ROA = 100/500=0.20 → fail
    s = _baseline_statements(ocf_t=20)
    _, sig = compute_fscore(s, AS_OF)
    assert sig["F4_accruals"] == 0

def test_f5_delta_leverage_pass():
    # LT debt lower: 50 vs 60 → leverage decreased → pass
    s = _baseline_statements(lt_debt_t=50, lt_debt_t1=60)
    _, sig = compute_fscore(s, AS_OF)
    assert sig["F5_delta_leverage"] == 1

def test_f5_delta_leverage_fail():
    # LT debt higher: 80 vs 60 → leverage increased → fail
    s = _baseline_statements(lt_debt_t=80, lt_debt_t1=60)
    _, sig = compute_fscore(s, AS_OF)
    assert sig["F5_delta_leverage"] == 0

def test_f6_delta_current_ratio_pass():
    # CR_t = 200/100=2.0, CR_t1 = 180/100=1.8 → improved → pass
    s = _baseline_statements()
    _, sig = compute_fscore(s, AS_OF)
    assert sig["F6_delta_current_ratio"] == 1

def test_f6_delta_current_ratio_fail():
    # CR_t = 150/100=1.5, CR_t1 = 180/100=1.8 → worsened → fail
    s = _baseline_statements(curr_assets_t=150)
    _, sig = compute_fscore(s, AS_OF)
    assert sig["F6_delta_current_ratio"] == 0

def test_f7_no_dilution_pass():
    s = _baseline_statements(shares_t=100, shares_t1=100)
    _, sig = compute_fscore(s, AS_OF)
    assert sig["F7_no_dilution"] == 1

def test_f7_no_dilution_fail():
    s = _baseline_statements(shares_t=110, shares_t1=100)
    _, sig = compute_fscore(s, AS_OF)
    assert sig["F7_no_dilution"] == 0

def test_f8_delta_gross_margin_pass():
    # GM_t = 160/400=0.40, GM_t1 = 130/360=0.361 → improved
    s = _baseline_statements()
    _, sig = compute_fscore(s, AS_OF)
    assert sig["F8_delta_gross_margin"] == 1

def test_f8_delta_gross_margin_fail():
    # GM_t = 100/400=0.25, GM_t1 = 130/360=0.361 → worsened
    s = _baseline_statements(gross_t=100)
    _, sig = compute_fscore(s, AS_OF)
    assert sig["F8_delta_gross_margin"] == 0

def test_f9_delta_asset_turnover_pass():
    # AT_t = 400/500=0.80, AT_t1 = 360/480=0.75 → improved
    s = _baseline_statements()
    _, sig = compute_fscore(s, AS_OF)
    assert sig["F9_delta_asset_turnover"] == 1

def test_f9_delta_asset_turnover_fail():
    # AT_t = 200/500=0.40, AT_t1 = 360/480=0.75 → worsened
    s = _baseline_statements(revenue_t=200)
    _, sig = compute_fscore(s, AS_OF)
    assert sig["F9_delta_asset_turnover"] == 0


# ── aggregate score ───────────────────────────────────────────────────────────

def test_perfect_score():
    s = _baseline_statements()
    score, _ = compute_fscore(s, AS_OF)
    assert score == 9

def test_score_all_fail():
    # OCF_t=-200 → OCF/assets=-0.40 < ROA=-0.20 → F4 fails (high accruals)
    s = _baseline_statements(
        net_income_t=-100,   # F1, F3 fail; ROA=-0.20
        ocf_t=-200,          # F2 fail; OCF/assets=-0.40 < ROA=-0.20 → F4 fail
        lt_debt_t=200,       # F5 fail: leverage increased
        curr_assets_t=50,    # F6 fail: current ratio worsened
        shares_t=200,        # F7 fail: dilution occurred
        gross_t=10,          # F8 fail: gross margin worsened
        revenue_t=50,        # F9 fail: asset turnover worsened
    )
    score, _ = compute_fscore(s, AS_OF)
    assert score == 0

def test_empty_statements_returns_zero():
    score, signals = compute_fscore({}, AS_OF)
    assert score == 0
    assert all(v is None for v in signals.values())


# ── compute_all_fscores / filter_by_fscore ────────────────────────────────────

def test_compute_all_fscores_two_tickers():
    stmt_a = _baseline_statements()            # score = 9
    stmt_b = _baseline_statements(net_income_t=-50)  # F1+F3+F4 fail → score ≤ 6
    all_stmts = {"AAPL": stmt_a, "GOOG": stmt_b}
    df = compute_all_fscores(["AAPL", "GOOG"], all_stmts, AS_OF)
    assert df.loc[df["ticker"] == "AAPL", "fscore"].iloc[0] == 9
    assert df.loc[df["ticker"] == "GOOG", "fscore"].iloc[0] < 9


def test_filter_by_fscore_threshold():
    stmt_a = _baseline_statements()            # score = 9 → passes
    stmt_b = _baseline_statements(net_income_t=-50, ocf_t=-1)  # low score
    all_stmts = {f"T{i}": stmt_a for i in range(10)}
    all_stmts["LOW"] = stmt_b
    tickers = list(all_stmts.keys())
    result = filter_by_fscore(tickers, all_stmts, AS_OF, threshold=8, min_count=5)
    assert (result["fscore"] >= 8).all()
    assert result["effective_threshold"].iloc[0] == 8


def test_filter_by_fscore_lowers_threshold():
    # Only 2 stocks with score ≥ 8; threshold lowers to get ≥ 10
    high = _baseline_statements()      # score = 9
    low  = _baseline_statements(net_income_t=-50, ocf_t=-1, lt_debt_t=200,
                                  curr_assets_t=50, gross_t=10, revenue_t=50)
    all_stmts = {"H1": high, "H2": high}
    for i in range(10):
        all_stmts[f"L{i}"] = low
    tickers = list(all_stmts.keys())
    result = filter_by_fscore(tickers, all_stmts, AS_OF, threshold=8, min_count=10)
    # Should have lowered threshold to include more stocks
    assert result["effective_threshold"].iloc[0] < 8
    assert len(result) >= 10
