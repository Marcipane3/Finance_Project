"""
Live recommendation engine for Track A.

Generates A1 (full rebalance) and A2 (buy-only capital deployment) recommendations
for the current quarter using today's data.

Usage:
    rec = run_live(config, current_holdings_path, new_capital_eur=3000)
    print(format_recommendation(rec))
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from track_a.src.backtest import (
    _existing_weighted_returns,
    _fixed_fee_eur,
    _load_sp500_tickers,
    _load_spy,
    _scale_mu0,
    _trading_days_between,
)
from track_a.src.fscore import filter_by_fscore
from track_a.src.fundamentals import fetch_fundamentals
from track_a.src.optimizer import OptimizeResult, solve_a1, solve_a2
from track_a.src.returns import estimate_mvn, fetch_prices, simulate_scenarios

logger = logging.getLogger(__name__)

_HOLDINGS_PATH = Path(__file__).parent.parent / "holdings.csv"
_HOLDINGS_SCHEMA = ["ticker", "shares", "entry_price", "entry_date", "status"]


@dataclass
class LiveRecommendation:
    as_of: date
    horizon_days: int

    # A1 — full rebalance
    a1_buy:  list[dict]     # [{ticker, weight, approx_eur}]
    a1_sell: list[dict]     # [{ticker, weight_before, weight_after, approx_eur_change}]
    a1_keep: list[dict]     # [{ticker, weight}]
    a1_cvar: float
    a1_expected_return: float
    a1_tc_estimate_eur: float
    a1_status: str

    # A2 — buy-only
    a2_new_positions: list[dict]   # [{ticker, weight_in_combined, approx_eur}]
    a2_combined_cvar: float
    a2_combined_expected_return: float
    a2_tc_estimate_eur: float
    a2_status: str

    # Context
    current_nav_eur: float
    new_capital_eur: float
    n_eligible: int
    effective_threshold: int

    # Warnings
    warnings: list[str] = field(default_factory=list)


def run_live(
    config: dict,
    holdings_path: Path | None = None,
    new_capital_eur: float | None = None,
    force_refresh: bool = False,
) -> LiveRecommendation:
    """Generate A1 + A2 recommendations for the current quarter.

    Reads current holdings from holdings.csv to determine existing portfolio.
    """
    a_cfg    = config["track_a"]
    opt_cfg  = a_cfg["optimizer"]
    ret_cfg  = a_cfg["returns"]
    fs_cfg   = a_cfg["fscore"]
    cadence  = "quarterly"      # live mode always runs quarterly

    new_cap  = new_capital_eur if new_capital_eur is not None else float(a_cfg["new_capital_per_period_eur"])
    h_path   = holdings_path or _HOLDINGS_PATH
    mu0_ann  = a_cfg.get("live_mu0_annual", 0.10)   # default 10% for live mode
    mu0_h    = _scale_mu0(mu0_ann, cadence)

    today    = pd.Timestamp(date.today())
    warnings: list[str] = []

    # ── load current holdings ─────────────────────────────────────────────────
    current_holdings = _load_holdings(h_path)
    current_nav = _estimate_nav(current_holdings, a_cfg)
    total_nav   = current_nav + new_cap
    logger.info("Live: current NAV ≈€%.0f, new capital €%.0f, total €%.0f",
                current_nav, new_cap, total_nav)

    # ── data ──────────────────────────────────────────────────────────────────
    sp500_tickers = _load_sp500_tickers()
    closes = fetch_prices(sp500_tickers, start_date=a_cfg["price_history_start"],
                           force_refresh=force_refresh)
    all_stmts = fetch_fundamentals(sp500_tickers, force_refresh=force_refresh)

    # ── F-Score filter ────────────────────────────────────────────────────────
    eligible_df = filter_by_fscore(
        sp500_tickers, all_stmts, as_of_date=today,
        threshold=fs_cfg["threshold"], min_count=fs_cfg["min_stocks"],
    )
    eligible      = eligible_df["ticker"].tolist()
    eff_threshold = int(eligible_df["effective_threshold"].iloc[0]) if len(eligible_df) else fs_cfg["threshold"]

    if eff_threshold < fs_cfg["threshold"]:
        warnings.append(f"F-Score threshold lowered to {eff_threshold} (normally {fs_cfg['threshold']})")
    logger.info("Live: %d eligible tickers (F-Score ≥ %d)", len(eligible), eff_threshold)

    avail = [t for t in eligible if t in closes.columns]
    if len(avail) < opt_cfg["k_min"]:
        warnings.append(f"Only {len(avail)} price-available tickers — cannot optimize")
        return _empty_rec(today, current_nav, new_cap, len(eligible), eff_threshold, warnings)

    # Estimate horizon in trading days (~63 for quarterly)
    next_qend = _next_quarter_end(today)
    horizon_days = _trading_days_between(closes, today, next_qend) or 63

    # ── MVN + scenarios ───────────────────────────────────────────────────────
    mu, sigma = estimate_mvn(closes, avail, as_of_date=today,
                              lookback_days=ret_cfg["lookback_days"])
    seed = int(today.timestamp()) % (2 ** 31)
    scenarios = simulate_scenarios(mu, sigma, horizon_days=horizon_days,
                                    n_sims=ret_cfg["n_simulations"], seed=seed)

    # ── current portfolio weights ─────────────────────────────────────────────
    ticker_idx   = {t: i for i, t in enumerate(avail)}
    prev_weights = _holdings_to_weights(current_holdings, avail, current_nav)
    new_cap_frac = new_cap / total_nav

    # ── A1: full rebalance ────────────────────────────────────────────────────
    a1_result = solve_a1(
        scenarios=scenarios,
        tickers=avail,
        prev_weights=prev_weights,
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
    if a1_result.status != "optimal":
        warnings.append(f"A1 optimizer: {a1_result.status}")

    a1_buy, a1_sell, a1_keep = _diff_weights(
        prev_w=dict(zip(avail, prev_weights)),
        new_w=dict(zip(avail, a1_result.weights)) if a1_result.status == "optimal" else {},
        total_nav=total_nav,
    )
    a1_tc_eur = len(a1_buy) * _fixed_fee_eur(config) + a1_result.tc_paid_fraction * total_nav

    # ── A2: buy-only ──────────────────────────────────────────────────────────
    existing_tickers  = list(current_holdings["ticker"]) if not current_holdings.empty else []
    new_candidates    = [t for t in avail if t not in existing_tickers]
    a2_existing_w     = {t: float(w) for t, w in zip(avail, prev_weights) if w > 0}
    existing_ret      = _existing_weighted_returns(scenarios, avail, a2_existing_w)

    if new_candidates and new_cap > 0:
        new_idx   = [ticker_idx[t] for t in new_candidates]
        new_scen  = scenarios[:, new_idx]

        a2_result = solve_a2(
            new_scenarios=new_scen,
            new_tickers=new_candidates,
            existing_weighted_returns=existing_ret,
            new_capital_frac=new_cap_frac,
            mu0=mu0_h,
            beta=opt_cfg["beta"],
            k_min_new=a_cfg["a2"]["k_min_new"],
            k_max_new=a_cfg["a2"]["k_max_new"],
            w_min_new=opt_cfg["w_min"],
            w_max_new=opt_cfg["w_max"],
            time_limit_s=opt_cfg["solver_time_limit_s"],
        )
        a2_new_positions = [
            {
                "ticker":          new_candidates[j],
                "weight_combined": float(a2_result.weights[j]),
                "approx_eur":      round(float(a2_result.weights[j]) * total_nav),
            }
            for j in range(len(new_candidates))
            if a2_result.weights[j] > 1e-4
        ]
        if a2_result.status != "optimal":
            warnings.append(f"A2 optimizer: {a2_result.status}")
    else:
        a2_result = OptimizeResult(np.zeros(0), 0.0, 0.0, 0.0, 0, "skipped", 0.0)
        a2_new_positions = []
        if not new_candidates:
            warnings.append("A2: all F-Score-eligible stocks already held — no new positions to add")

    a2_tc_eur = len(a2_new_positions) * _fixed_fee_eur(config)

    return LiveRecommendation(
        as_of=date.today(),
        horizon_days=horizon_days,
        a1_buy=a1_buy,
        a1_sell=a1_sell,
        a1_keep=a1_keep,
        a1_cvar=a1_result.cvar,
        a1_expected_return=a1_result.expected_return,
        a1_tc_estimate_eur=a1_tc_eur,
        a1_status=a1_result.status,
        a2_new_positions=a2_new_positions,
        a2_combined_cvar=a2_result.cvar,
        a2_combined_expected_return=a2_result.expected_return,
        a2_tc_estimate_eur=a2_tc_eur,
        a2_status=a2_result.status,
        current_nav_eur=current_nav,
        new_capital_eur=new_cap,
        n_eligible=len(eligible),
        effective_threshold=eff_threshold,
        warnings=warnings,
    )


def format_recommendation(rec: LiveRecommendation) -> str:
    """Render the recommendation as a markdown string."""
    total_nav = rec.current_nav_eur + rec.new_capital_eur
    lines = [
        f"# Track A — Live Recommendation",
        f"*{rec.as_of} · Horizon: {rec.horizon_days} trading days (~{rec.horizon_days // 21}m)*",
        f"",
        f"**Portfolio:** €{rec.current_nav_eur:,.0f} existing + €{rec.new_capital_eur:,.0f} new capital = €{total_nav:,.0f} total",
        f"**Universe:** {rec.n_eligible} stocks passed F-Score >= {rec.effective_threshold}",
        f"",
    ]

    if rec.warnings:
        lines += ["> **Warnings:**"]
        for w in rec.warnings:
            lines += [f"> - {w}"]
        lines += [""]

    # ── A1 ────────────────────────────────────────────────────────────────────
    lines += [
        "---",
        "",
        "## A1 — Full Rebalance",
        f"*Status: {rec.a1_status} · E[return]: {rec.a1_expected_return:.1%} · CVaR₁₀: {rec.a1_cvar:.1%} · Estimated TC: €{rec.a1_tc_estimate_eur:.0f}*",
        "",
    ]
    if rec.a1_buy:
        lines += ["**Buy (new/increased positions):**", ""]
        lines += ["| Ticker | Weight | ≈ EUR |", "|---|---|---|"]
        for p in sorted(rec.a1_buy, key=lambda x: -x["weight"]):
            lines.append(f"| {p['ticker']} | {p['weight']:.1%} | €{p['approx_eur']:,.0f} |")
        lines += [""]
    if rec.a1_sell:
        lines += ["**Sell / reduce:**", ""]
        lines += ["| Ticker | Before | After | Δ EUR |", "|---|---|---|---|"]
        for p in sorted(rec.a1_sell, key=lambda x: x["weight_after"]):
            lines.append(f"| {p['ticker']} | {p['weight_before']:.1%} | {p['weight_after']:.1%} | €{p['eur_change']:+,.0f} |")
        lines += [""]
    if rec.a1_keep:
        lines += ["**Keep (unchanged):**", ""]
        lines += ["| Ticker | Weight |", "|---|---|"]
        for p in sorted(rec.a1_keep, key=lambda x: -x["weight"]):
            lines.append(f"| {p['ticker']} | {p['weight']:.1%} |")
        lines += [""]

    # ── A2 ────────────────────────────────────────────────────────────────────
    lines += [
        "---",
        "",
        "## A2 — Capital Deployment (Buy-Only)",
        f"*Status: {rec.a2_status} · Combined E[return]: {rec.a2_combined_expected_return:.1%} · Combined CVaR₁₀: {rec.a2_combined_cvar:.1%} · Estimated TC: €{rec.a2_tc_estimate_eur:.0f}*",
        "",
        f"Deploy €{rec.new_capital_eur:,.0f} into new positions — existing holdings unchanged.",
        "",
    ]
    if rec.a2_new_positions:
        lines += ["| Ticker | Weight (combined portfolio) | ≈ EUR |", "|---|---|---|"]
        for p in sorted(rec.a2_new_positions, key=lambda x: -x["approx_eur"]):
            lines.append(f"| {p['ticker']} | {p['weight_combined']:.1%} | €{p['approx_eur']:,.0f} |")
    else:
        lines += ["*No new positions recommended.*"]

    return "\n".join(lines)


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_holdings(path: Path) -> pd.DataFrame:
    if path.exists():
        try:
            df = pd.read_csv(path)
            if "ticker" in df.columns and "status" in df.columns:
                return df[df["status"] == "held"].reset_index(drop=True)
        except Exception:
            pass
    return pd.DataFrame(columns=_HOLDINGS_SCHEMA)


def _estimate_nav(holdings: pd.DataFrame, a_cfg: dict) -> float:
    """Estimate current portfolio NAV. Falls back to initial_capital if holdings empty."""
    if holdings.empty:
        return float(a_cfg["initial_capital_eur"])
    # TODO: fetch current prices and compute mark-to-market NAV
    # For now: entry_price × shares as a proxy
    if "entry_price" in holdings.columns and "shares" in holdings.columns:
        try:
            return float((holdings["entry_price"] * holdings["shares"]).sum())
        except Exception:
            pass
    return float(a_cfg["initial_capital_eur"])


def _holdings_to_weights(
    holdings: pd.DataFrame,
    avail: list[str],
    nav: float,
) -> np.ndarray:
    """Convert holdings CSV to weight vector aligned with avail list."""
    weights = np.zeros(len(avail))
    if holdings.empty or nav <= 0:
        return weights
    ticker_idx = {t: i for i, t in enumerate(avail)}
    for _, row in holdings.iterrows():
        t = str(row.get("ticker", ""))
        if t in ticker_idx:
            position_value = float(row.get("entry_price", 0)) * float(row.get("shares", 0))
            weights[ticker_idx[t]] = position_value / nav
    total = weights.sum()
    if total > 0:
        weights /= total   # renormalize to sum=1 (mark-to-market not accounted for)
    return weights


def _diff_weights(
    prev_w: dict[str, float],
    new_w: dict[str, float],
    total_nav: float,
) -> tuple[list, list, list]:
    """Split new vs. old weights into buy / sell / keep."""
    all_tickers = set(prev_w) | set(new_w)
    buy, sell, keep = [], [], []
    for t in all_tickers:
        p = prev_w.get(t, 0.0)
        n = new_w.get(t, 0.0)
        if n > p + 0.005:
            buy.append({"ticker": t, "weight": n, "approx_eur": round(n * total_nav)})
        elif p > n + 0.005:
            sell.append({
                "ticker": t, "weight_before": p, "weight_after": n,
                "eur_change": round((n - p) * total_nav),
            })
        elif n > 1e-4:
            keep.append({"ticker": t, "weight": n})
    return buy, sell, keep


def _next_quarter_end(today: pd.Timestamp) -> pd.Timestamp:
    m = today.month
    if m <= 3:   return pd.Timestamp(today.year, 3, 31)
    if m <= 6:   return pd.Timestamp(today.year, 6, 30)
    if m <= 9:   return pd.Timestamp(today.year, 9, 30)
    return pd.Timestamp(today.year, 12, 31)


def _empty_rec(
    today: pd.Timestamp,
    current_nav: float,
    new_cap: float,
    n_eligible: int,
    eff_threshold: int,
    warnings: list[str],
) -> LiveRecommendation:
    return LiveRecommendation(
        as_of=today.date(),
        horizon_days=63,
        a1_buy=[], a1_sell=[], a1_keep=[],
        a1_cvar=float("nan"), a1_expected_return=float("nan"),
        a1_tc_estimate_eur=0.0, a1_status="skipped",
        a2_new_positions=[],
        a2_combined_cvar=float("nan"), a2_combined_expected_return=float("nan"),
        a2_tc_estimate_eur=0.0, a2_status="skipped",
        current_nav_eur=current_nav,
        new_capital_eur=new_cap,
        n_eligible=n_eligible,
        effective_threshold=eff_threshold,
        warnings=warnings,
    )
