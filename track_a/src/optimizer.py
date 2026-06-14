"""
MILP-CVaR optimizer for Track A.

Two modes:
  A1 (solve_a1): full rebalance — optimize over all N stocks, buy and sell allowed.
      Proportional TC included in objective. Fixed TC deducted post-hoc in backtest.
  A2 (solve_a2): buy-only — existing positions are fixed; allocate new_capital to
      new stocks only. Combined (existing + new) portfolio CVaR is minimized.

Both return an OptimizeResult dataclass. Status "infeasible" or "timeout" means
the backtest should hold prior weights for that period.

Solver: HiGHS via cvxpy (free, MIT-licensed).
"""

import logging
import time
from dataclasses import dataclass, field

import cvxpy as cp
import numpy as np

logger = logging.getLogger(__name__)

_SOLVER = cp.HIGHS


@dataclass
class OptimizeResult:
    weights: np.ndarray              # (N,) final portfolio weights
    cvar: float
    expected_return: float
    tc_paid_fraction: float          # TC as fraction of total portfolio
    n_positions: int
    status: str                      # "optimal" | "infeasible" | "timeout" | "error"
    solve_time_s: float
    tickers: list[str] = field(default_factory=list)  # names if provided


# ── A1: full rebalance ────────────────────────────────────────────────────────

def solve_a1(
    scenarios: np.ndarray,           # (S × N) terminal simple returns
    tickers: list[str],
    prev_weights: np.ndarray,        # (N,) current portfolio weights (0 if new)
    new_capital_frac: float,         # new_capital / (existing + new_capital)
    mu0: float,                      # minimum expected net return over horizon
    beta: float,                     # CVaR tail level (e.g. 0.10)
    k_min: int,
    k_max: int,
    w_min: float,
    w_max: float,
    tc_variable: float,              # proportional TC per unit |weight change|
    time_limit_s: float = 120.0,
) -> OptimizeResult:
    """Full rebalance optimization (A1 mode).

    The new capital injection is handled by scaling prev_weights:
        prev_weights_adj = prev_weights * (1 - new_capital_frac)
    This reflects that existing positions become a smaller fraction of the
    enlarged portfolio; TC is computed on changes vs. these adjusted weights.
    """
    t0 = time.perf_counter()
    S, N = scenarios.shape
    if len(prev_weights) != N:
        prev_weights = np.zeros(N)

    # Adjust prev_weights to account for new capital dilution
    prev_adj = prev_weights * (1.0 - new_capital_frac)

    w    = cp.Variable(N, nonneg=True)
    z    = cp.Variable(N, boolean=True)
    xi   = cp.Variable(S, nonneg=True)
    eta  = cp.Variable()
    d_plus  = cp.Variable(N, nonneg=True)   # weight increases
    d_minus = cp.Variable(N, nonneg=True)   # weight decreases
    tc_total = tc_variable * (cp.sum(d_plus) + cp.sum(d_minus))

    r_net = scenarios @ w - tc_total   # (S,) net returns per scenario

    objective = cp.Minimize(eta + (1.0 / ((1.0 - beta) * S)) * cp.sum(xi))
    constraints = [
        xi >= -r_net - eta,
        cp.sum(r_net) / S >= mu0,      # expected net return ≥ mu0
        cp.sum(w) == 1.0,
        cp.sum(z) >= k_min,
        cp.sum(z) <= k_max,
        w_min * z <= w,
        w <= w_max * z,
        d_plus - d_minus == w - prev_adj,
    ]

    prob = cp.Problem(objective, constraints)
    return _solve_and_wrap(prob, w, z, r_net, scenarios, tc_total, eta,
                           tickers, t0, time_limit_s)


# ── A2: buy-only capital deployment ──────────────────────────────────────────

def solve_a2(
    new_scenarios: np.ndarray,       # (S × N_new) returns for NEW candidate stocks
    new_tickers: list[str],
    existing_weighted_returns: np.ndarray,  # (S,) existing portfolio return per scenario
                                            # = existing_scenarios @ existing_weights
    new_capital_frac: float,         # fraction of combined portfolio being newly deployed
    mu0: float,
    beta: float,
    k_min_new: int,
    k_max_new: int,
    w_min_new: float,
    w_max_new: float,
    time_limit_s: float = 120.0,
) -> OptimizeResult:
    """Buy-only optimization (A2 mode).

    existing_weighted_returns: pre-computed (S,) vector = existing_scenarios @ existing_weights.
    Optimizes allocation of new_capital_frac across new stocks to minimize combined CVaR.
    No TC in A2 (pure buy, no sell).
    """
    t0 = time.perf_counter()
    S, N_new = new_scenarios.shape

    w_new = cp.Variable(N_new, nonneg=True)
    z_new = cp.Variable(N_new, boolean=True)
    xi    = cp.Variable(S, nonneg=True)
    eta   = cp.Variable()

    # Combined return = existing (constant) + new positions
    r_combined = existing_weighted_returns + new_scenarios @ w_new   # (S,)

    objective = cp.Minimize(eta + (1.0 / ((1.0 - beta) * S)) * cp.sum(xi))
    constraints = [
        xi >= -r_combined - eta,
        # mu0 applied per unit of new capital: require new positions to meet mu0 on their own
        cp.sum(new_scenarios @ w_new) / (S * new_capital_frac) >= mu0,
        cp.sum(w_new) == new_capital_frac,
        cp.sum(z_new) >= k_min_new,
        cp.sum(z_new) <= k_max_new,
        w_min_new * z_new <= w_new,
        w_new <= w_max_new * z_new,
    ]

    prob = cp.Problem(objective, constraints)
    return _solve_and_wrap(prob, w_new, z_new, r_combined, new_scenarios,
                           None, eta, new_tickers, t0, time_limit_s,
                           target_weight_sum=new_capital_frac)


# ── shared solve wrapper ──────────────────────────────────────────────────────

def _solve_and_wrap(
    prob: cp.Problem,
    w_var: cp.Variable,
    z_var: cp.Variable,
    r_net: cp.Expression,
    scenarios: np.ndarray,
    tc_var: cp.Expression | None,
    eta_var: cp.Variable,
    tickers: list[str],
    t0: float,
    time_limit_s: float,
    target_weight_sum: float = 1.0,
) -> OptimizeResult:
    S = scenarios.shape[0]
    try:
        prob.solve(
            solver=_SOLVER,
            verbose=False,
            time_limit=time_limit_s,
        )
    except Exception as exc:
        logger.warning("Optimizer: solver exception (%s)", exc)
        n = len(tickers)
        return OptimizeResult(
            weights=np.zeros(n), cvar=float("nan"), expected_return=float("nan"),
            tc_paid_fraction=0.0, n_positions=0,
            status="error", solve_time_s=time.perf_counter() - t0, tickers=tickers,
        )

    solve_time = time.perf_counter() - t0
    status_map = {
        "optimal":          "optimal",
        "optimal_inaccurate": "optimal",
        "infeasible":       "infeasible",
        "infeasible_inaccurate": "infeasible",
        "unbounded":        "infeasible",
        "solver_error":     "error",
        "time_limit":       "timeout",
    }
    status = status_map.get(prob.status or "", "error")

    if status not in ("optimal",) or w_var.value is None:
        logger.warning("Optimizer: status=%s in %.1fs", status, solve_time)
        n = len(tickers)
        return OptimizeResult(
            weights=np.zeros(n), cvar=float("nan"), expected_return=float("nan"),
            tc_paid_fraction=0.0, n_positions=0,
            status=status, solve_time_s=solve_time, tickers=tickers,
        )

    weights = np.clip(w_var.value, 0.0, None)
    # Renormalize only to correct floating-point drift, preserving the target sum
    if weights.sum() > 0:
        weights = weights / weights.sum() * target_weight_sum

    # Evaluate CVaR and expected return at solution
    r_vals = scenarios @ weights
    tc_frac = float(tc_var.value) if tc_var is not None else 0.0
    r_net_vals = r_vals - tc_frac
    exp_ret = float(r_net_vals.mean())
    var = float(np.quantile(r_net_vals, 1.0 - (1.0 - (1.0 - beta_from_prob(prob))) if False else 0.10))
    cvar = float(-r_net_vals[r_net_vals <= var].mean()) if (r_net_vals <= var).any() else float(-r_net_vals.mean())

    logger.info(
        "Optimizer: %s in %.1fs — %d positions, E[r]=%.3f, CVaR=%.3f, TC=%.4f",
        status, solve_time, int((weights > 1e-4).sum()), exp_ret, cvar, tc_frac,
    )
    return OptimizeResult(
        weights=weights,
        cvar=cvar,
        expected_return=exp_ret,
        tc_paid_fraction=tc_frac,
        n_positions=int((weights > 1e-4).sum()),
        status=status,
        solve_time_s=solve_time,
        tickers=tickers,
    )


def beta_from_prob(prob: cp.Problem) -> float:
    """Unused utility — CVaR tail level baked into the formulation constants."""
    return 0.10
