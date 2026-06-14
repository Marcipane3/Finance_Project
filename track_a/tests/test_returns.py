"""
Unit tests for track_a.src.returns — no network calls.
"""

import numpy as np
import pandas as pd
import pytest

from track_a.src.returns import estimate_mvn, simulate_scenarios


# ── fixtures ──────────────────────────────────────────────────────────────────

def _make_closes(n_days: int = 300, n_tickers: int = 5, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-02", periods=n_days, freq="B")
    prices = 100 * np.cumprod(1 + rng.normal(0.0005, 0.015, size=(n_days, n_tickers)), axis=0)
    tickers = [f"T{i}" for i in range(n_tickers)]
    return pd.DataFrame(prices, index=dates, columns=tickers)


CLOSES = _make_closes()
TICKERS = list(CLOSES.columns)
AS_OF = CLOSES.index[-1]


# ── estimate_mvn ──────────────────────────────────────────────────────────────

def test_estimate_mvn_shapes():
    mu, sigma = estimate_mvn(CLOSES, TICKERS, AS_OF)
    assert mu.shape == (len(TICKERS),)
    assert sigma.shape == (len(TICKERS), len(TICKERS))


def test_estimate_mvn_sigma_positive_definite():
    _, sigma = estimate_mvn(CLOSES, TICKERS, AS_OF)
    eigvals = np.linalg.eigvalsh(sigma)
    assert (eigvals > 0).all(), f"Eigenvalues not all positive: {eigvals}"


def test_estimate_mvn_sigma_symmetric():
    _, sigma = estimate_mvn(CLOSES, TICKERS, AS_OF)
    np.testing.assert_allclose(sigma, sigma.T, atol=1e-12)


def test_estimate_mvn_respects_as_of_date():
    # Requesting data only up to day 100 should give different mu than full window
    as_of_early = CLOSES.index[100]
    mu_full, _  = estimate_mvn(CLOSES, TICKERS, AS_OF)
    mu_early, _ = estimate_mvn(CLOSES, TICKERS, as_of_early)
    # They won't be identical (different windows)
    assert not np.allclose(mu_full, mu_early, atol=1e-6)


def test_estimate_mvn_empty_closes_returns_fallback():
    mu, sigma = estimate_mvn(pd.DataFrame(), ["X", "Y"], AS_OF)
    assert mu.shape == (2,)
    assert sigma.shape == (2, 2)
    assert (np.linalg.eigvalsh(sigma) > 0).all()


def test_estimate_mvn_missing_ticker_filled():
    # Request T0..T4 but only provide T0..T2
    mu, sigma = estimate_mvn(CLOSES[["T0", "T1", "T2"]], TICKERS, AS_OF)
    assert mu.shape == (len(TICKERS),)
    # Missing tickers get median fill — should be finite
    assert np.isfinite(mu).all()
    assert np.isfinite(sigma).all()


# ── simulate_scenarios ────────────────────────────────────────────────────────

def test_simulate_scenarios_shape():
    mu    = np.array([0.0005, 0.0003])
    sigma = np.array([[0.0004, 0.0001], [0.0001, 0.0003]])
    scenarios = simulate_scenarios(mu, sigma, horizon_days=63, n_sims=500)
    assert scenarios.shape == (500, 2)


def test_simulate_scenarios_finite():
    mu    = np.array([0.0005, 0.0003])
    sigma = np.array([[0.0004, 0.0001], [0.0001, 0.0003]])
    scenarios = simulate_scenarios(mu, sigma, horizon_days=63, n_sims=200)
    assert np.isfinite(scenarios).all()


def test_simulate_scenarios_reproducible():
    mu    = np.array([0.0005, 0.0003])
    sigma = np.array([[0.0004, 0.0001], [0.0001, 0.0003]])
    s1 = simulate_scenarios(mu, sigma, horizon_days=63, n_sims=100, seed=42)
    s2 = simulate_scenarios(mu, sigma, horizon_days=63, n_sims=100, seed=42)
    np.testing.assert_array_equal(s1, s2)


def test_simulate_scenarios_mean_close_to_expected():
    # With 5000 sims, sample mean should be close to exp(mu*h) - 1
    mu    = np.array([0.001, 0.0])
    sigma = np.diag([0.0001, 0.0001])   # tiny vol to reduce noise
    h = 252
    scenarios = simulate_scenarios(mu, sigma, horizon_days=h, n_sims=10000, seed=7)
    expected = np.exp(mu * h) - 1
    np.testing.assert_allclose(scenarios.mean(axis=0), expected, atol=0.05)


def test_simulate_scenarios_horizon_scaling():
    # Longer horizon → larger variance
    mu    = np.zeros(2)
    sigma = np.diag([0.0002, 0.0002])
    s_short = simulate_scenarios(mu, sigma, horizon_days=21,  n_sims=2000, seed=1)
    s_long  = simulate_scenarios(mu, sigma, horizon_days=252, n_sims=2000, seed=1)
    assert s_short.std() < s_long.std()
