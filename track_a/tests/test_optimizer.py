"""
Unit tests for track_a.src.optimizer — no network calls, small toy problems.
"""

import numpy as np
import pytest

from track_a.src.optimizer import OptimizeResult, solve_a1, solve_a2


# ── shared fixtures ───────────────────────────────────────────────────────────

def _make_scenarios(n_stocks: int = 5, n_sims: int = 200, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # Stock 0 has higher expected return; stocks 1-4 are lower
    means  = [0.05] + [0.02] * (n_stocks - 1)
    stdevs = [0.10] * n_stocks
    return rng.normal(
        np.array(means) * 0.25,    # quarterly
        np.array(stdevs) * np.sqrt(0.25),
        size=(n_sims, n_stocks),
    )


TICKERS  = ["A", "B", "C", "D", "E"]
SCENARIOS = _make_scenarios(n_stocks=5, n_sims=300)


# ── solve_a1 ──────────────────────────────────────────────────────────────────

def test_a1_optimal_status():
    result = solve_a1(
        scenarios=SCENARIOS,
        tickers=TICKERS,
        prev_weights=np.zeros(5),
        new_capital_frac=0.0,
        mu0=-0.05,    # permissive: just minimize CVaR
        beta=0.10,
        k_min=2,
        k_max=5,
        w_min=0.10,
        w_max=0.60,
        tc_variable=0.0045,
    )
    assert result.status == "optimal"


def test_a1_weights_sum_to_one():
    result = solve_a1(
        scenarios=SCENARIOS,
        tickers=TICKERS,
        prev_weights=np.zeros(5),
        new_capital_frac=0.0,
        mu0=-0.05,    # permissive: just minimize CVaR
        beta=0.10,
        k_min=2,
        k_max=5,
        w_min=0.10,
        w_max=0.60,
        tc_variable=0.0045,
    )
    assert result.status == "optimal"
    np.testing.assert_allclose(result.weights.sum(), 1.0, atol=1e-4)


def test_a1_cardinality_respected():
    result = solve_a1(
        scenarios=SCENARIOS,
        tickers=TICKERS,
        prev_weights=np.zeros(5),
        new_capital_frac=0.0,
        mu0=0.00,
        beta=0.10,
        k_min=2,
        k_max=3,
        w_min=0.10,
        w_max=0.60,
        tc_variable=0.0045,
    )
    assert result.status == "optimal"
    n_pos = int((result.weights > 1e-4).sum())
    assert 2 <= n_pos <= 3


def test_a1_weight_bounds_respected():
    result = solve_a1(
        scenarios=SCENARIOS,
        tickers=TICKERS,
        prev_weights=np.zeros(5),
        new_capital_frac=0.0,
        mu0=0.00,
        beta=0.10,
        k_min=2,
        k_max=5,
        w_min=0.10,
        w_max=0.50,
        tc_variable=0.0045,
    )
    assert result.status == "optimal"
    active = result.weights[result.weights > 1e-4]
    assert (active >= 0.10 - 1e-4).all()
    assert (active <= 0.50 + 1e-4).all()


def test_a1_infeasible_on_impossible_mu0():
    # mu0 of 100% quarterly return is infeasible with these scenarios
    result = solve_a1(
        scenarios=SCENARIOS,
        tickers=TICKERS,
        prev_weights=np.zeros(5),
        new_capital_frac=0.0,
        mu0=100.0,      # impossible
        beta=0.10,
        k_min=2,
        k_max=5,
        w_min=0.10,
        w_max=0.60,
        tc_variable=0.0045,
    )
    assert result.status in ("infeasible", "error")


def test_a1_new_capital_dilutes_prev_weights():
    # With 50% new capital, prev_weights of [0.5, 0.5, 0, 0, 0] become [0.25, 0.25, 0, 0, 0]
    # The optimizer should still produce a valid solution
    result = solve_a1(
        scenarios=SCENARIOS,
        tickers=TICKERS,
        prev_weights=np.array([0.5, 0.5, 0.0, 0.0, 0.0]),
        new_capital_frac=0.5,
        mu0=0.00,
        beta=0.10,
        k_min=2,
        k_max=5,
        w_min=0.10,
        w_max=0.60,
        tc_variable=0.0045,
    )
    assert result.status == "optimal"
    np.testing.assert_allclose(result.weights.sum(), 1.0, atol=1e-4)


def test_a1_returns_finite_metrics():
    result = solve_a1(
        scenarios=SCENARIOS,
        tickers=TICKERS,
        prev_weights=np.zeros(5),
        new_capital_frac=0.0,
        mu0=0.00,
        beta=0.10,
        k_min=2,
        k_max=5,
        w_min=0.10,
        w_max=0.60,
        tc_variable=0.0045,
    )
    assert result.status == "optimal"
    assert np.isfinite(result.cvar)
    assert np.isfinite(result.expected_return)


# ── solve_a2 ──────────────────────────────────────────────────────────────────

def _existing_returns(seed: int = 99) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.02, 0.05, size=300)   # (S,) existing portfolio contribution


def test_a2_optimal_status():
    result = solve_a2(
        new_scenarios=SCENARIOS[:, :3],
        new_tickers=["X", "Y", "Z"],
        existing_weighted_returns=_existing_returns(),
        new_capital_frac=0.12,
        mu0=-0.01,
        beta=0.10,
        k_min_new=1,
        k_max_new=3,
        w_min_new=0.03,
        w_max_new=0.12,
    )
    assert result.status == "optimal"


def test_a2_new_weights_sum_to_new_capital_frac():
    new_frac = 0.12
    result = solve_a2(
        new_scenarios=SCENARIOS[:, :3],
        new_tickers=["X", "Y", "Z"],
        existing_weighted_returns=_existing_returns(),
        new_capital_frac=new_frac,
        mu0=-0.01,
        beta=0.10,
        k_min_new=1,
        k_max_new=3,
        w_min_new=0.03,
        w_max_new=0.12,
    )
    assert result.status == "optimal"
    np.testing.assert_allclose(result.weights.sum(), new_frac, atol=1e-4)


def test_a2_cardinality_respected():
    result = solve_a2(
        new_scenarios=SCENARIOS,
        new_tickers=TICKERS,
        existing_weighted_returns=_existing_returns(),
        new_capital_frac=0.15,
        mu0=-0.05,
        beta=0.10,
        k_min_new=1,
        k_max_new=2,
        w_min_new=0.03,
        w_max_new=0.12,
    )
    assert result.status == "optimal"
    n_pos = int((result.weights > 1e-4).sum())
    assert 1 <= n_pos <= 2


def test_a2_no_negative_weights():
    result = solve_a2(
        new_scenarios=SCENARIOS[:, :3],
        new_tickers=["X", "Y", "Z"],
        existing_weighted_returns=_existing_returns(),
        new_capital_frac=0.10,
        mu0=-0.01,
        beta=0.10,
        k_min_new=1,
        k_max_new=3,
        w_min_new=0.03,
        w_max_new=0.10,
    )
    assert result.status == "optimal"
    assert (result.weights >= -1e-6).all(), "A2 should never produce negative weights"
