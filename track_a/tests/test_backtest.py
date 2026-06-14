"""
Unit tests for track_a.src.backtest and track_a.src.metrics.
Uses synthetic data — no network calls.
"""

import numpy as np
import pandas as pd
import pytest

from track_a.src.backtest import (
    _existing_weighted_returns,
    _mark_to_market_a2,
    _rebal_schedule,
    _scale_mu0,
    _ticker_return,
    _trading_days_between,
)
from track_a.src.metrics import (
    _annualized_sharpe,
    _cagr,
    _cvar,
    _max_drawdown,
    build_nav_series,
    compute_metrics,
)


# ── _rebal_schedule ───────────────────────────────────────────────────────────

def test_rebal_schedule_quarterly_has_multiple_dates():
    dates = _rebal_schedule("quarterly", pd.Timestamp("2021-01-01"))
    assert len(dates) >= 5   # at least 5 quarters in 2021–present


def test_rebal_schedule_yearly_has_multiple_dates():
    dates = _rebal_schedule("yearly", pd.Timestamp("2021-01-01"))
    assert len(dates) >= 3


def test_rebal_schedule_sorted():
    dates = _rebal_schedule("quarterly", pd.Timestamp("2021-01-01"))
    assert dates == sorted(dates)


def test_rebal_schedule_unknown_cadence():
    with pytest.raises(ValueError):
        _rebal_schedule("weekly", pd.Timestamp("2021-01-01"))


# ── _scale_mu0 ────────────────────────────────────────────────────────────────

def test_scale_mu0_quarterly():
    mu_q = _scale_mu0(0.10, "quarterly")
    # (1.10)^0.25 - 1 ≈ 0.02411
    assert abs(mu_q - 0.02411) < 1e-4


def test_scale_mu0_yearly():
    assert _scale_mu0(0.10, "yearly") == 0.10


# ── _trading_days_between ─────────────────────────────────────────────────────

def test_trading_days_between():
    dates = pd.date_range("2023-01-02", periods=100, freq="B")
    closes = pd.DataFrame({"A": np.ones(100)}, index=dates)
    t_start = dates[0]
    t_end   = dates[62]
    n = _trading_days_between(closes, t_start, t_end)
    assert n == 62


def test_trading_days_between_fallback():
    closes = pd.DataFrame()
    n = _trading_days_between(closes, pd.Timestamp("2023-01-01"), pd.Timestamp("2023-04-01"))
    assert n == 63   # fallback


# ── _ticker_return ────────────────────────────────────────────────────────────

def test_ticker_return_basic():
    dates = pd.date_range("2023-01-02", periods=10, freq="B")
    closes = pd.DataFrame({"AAPL": [100, 101, 102, 103, 104, 105, 106, 107, 108, 110]},
                           index=dates)
    r = _ticker_return(closes, "AAPL", dates[0], dates[-1])
    assert abs(r - 0.10) < 1e-6


def test_ticker_return_missing_ticker():
    closes = pd.DataFrame({"AAPL": [100, 110]}, index=pd.date_range("2023-01-02", periods=2))
    r = _ticker_return(closes, "GOOG", pd.Timestamp("2023-01-02"), pd.Timestamp("2023-01-03"))
    assert r == 0.0


# ── _existing_weighted_returns ────────────────────────────────────────────────

def test_existing_weighted_returns():
    scenarios = np.array([[0.10, 0.05], [0.02, 0.03], [-0.01, 0.04]])
    avail = ["A", "B"]
    existing_w = {"A": 0.30, "B": 0.20}
    result = _existing_weighted_returns(scenarios, avail, existing_w)
    expected = 0.30 * scenarios[:, 0] + 0.20 * scenarios[:, 1]
    np.testing.assert_allclose(result, expected)


def test_existing_weighted_returns_empty():
    scenarios = np.zeros((5, 3))
    result = _existing_weighted_returns(scenarios, ["A", "B", "C"], {})
    np.testing.assert_array_equal(result, np.zeros(5))


# ── _mark_to_market_a2 ────────────────────────────────────────────────────────

def test_mark_to_market_a2():
    dates = pd.date_range("2023-01-02", periods=5, freq="B")
    closes = pd.DataFrame({"AAPL": [100, 100, 100, 100, 110]}, index=dates)
    holdings = {"AAPL": 1000.0}
    updated = _mark_to_market_a2(holdings, closes, dates[0], dates[-1])
    assert abs(updated["AAPL"] - 1100.0) < 1e-4


# ── metrics ───────────────────────────────────────────────────────────────────

def test_cagr_doubles_in_two_years():
    nav = pd.Series(
        [1000, 1414, 2000],
        index=pd.date_range("2020-01-01", periods=3, freq="365D"),
    )
    cagr = _cagr(nav)
    assert abs(cagr - 0.4142) < 0.01   # sqrt(2) - 1 ≈ 0.414


def test_max_drawdown_known():
    nav = pd.Series([100, 110, 90, 80, 95], index=pd.date_range("2020-01-01", periods=5))
    dd = _max_drawdown(nav)
    # Peak=110, trough=80 → drawdown = (80-110)/110 ≈ -0.2727
    assert abs(dd - (-0.2727)) < 0.001


def test_cvar_known():
    # Returns: [−0.10, −0.05, 0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35]
    returns = pd.Series([-0.10, -0.05, 0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35])
    cvar = _cvar(returns, tail_pct=0.10)
    # Bottom 10% = [-0.10] → CVaR = 0.10
    assert abs(cvar - 0.10) < 0.01


def test_compute_metrics_returns_expected_keys():
    nav = pd.Series(
        [1000 * (1.01) ** i for i in range(20)],
        index=pd.date_range("2021-01-01", periods=20, freq="QE"),
    )
    m = compute_metrics(nav)
    assert "cagr" in m
    assert "annualized_sharpe" in m
    assert "max_drawdown" in m
    assert "total_return" in m


def test_build_nav_series():
    df = pd.DataFrame({"date": pd.date_range("2021-01-01", periods=4, freq="QE"),
                        "nav_a1": [23000, 24000, 25000, 26000]})
    nav = build_nav_series(df, "nav_a1")
    assert len(nav) == 4
    assert nav.iloc[0] == 23000
