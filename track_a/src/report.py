"""
Report generator for Track A backtest results.

Produces:
  - Markdown comparison table (A1 vs A2 vs SPY, across μ₀ sweep)
  - NAV chart (matplotlib PNG)
  - Pareto frontier chart: return vs. max drawdown across μ₀ sweep

Usage:
    generate_report(all_results, config, spy_nav)
    # all_results: {(cadence, mu0): backtest_df}
"""

import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path(__file__).parent.parent / "output"


def generate_report(
    all_results: dict[tuple, pd.DataFrame],
    config: dict,
    spy_nav: pd.Series | None = None,
) -> Path:
    """Assemble and save the full backtest report.

    Parameters
    ----------
    all_results : {(cadence, mu0): backtest_df} from the μ₀ sweep
    config      : parsed config.yaml
    spy_nav     : optional SPY NAV series for benchmark comparison

    Returns
    -------
    Path to saved markdown report
    """
    from track_a.src.metrics import build_nav_series, compare_strategies, compute_metrics

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today()

    # ── per-run metrics ───────────────────────────────────────────────────────
    rows = []
    nav_series: dict[str, pd.Series] = {}
    for (cadence, mu0), df in all_results.items():
        if df.empty:
            continue
        nav_a1 = build_nav_series(df, "nav_a1")
        nav_a2 = build_nav_series(df, "nav_a2")
        m_a1 = compute_metrics(nav_a1, spy_nav)
        m_a2 = compute_metrics(nav_a2, spy_nav)

        label_a1 = f"A1 {cadence} μ₀={mu0:.0%}"
        label_a2 = f"A2 {cadence} μ₀={mu0:.0%}"
        nav_series[label_a1] = nav_a1
        nav_series[label_a2] = nav_a2

        for strategy, m, label in [("A1", m_a1, label_a1), ("A2", m_a2, label_a2)]:
            rows.append({
                "Strategy":  label,
                "Cadence":   cadence,
                "Mode":      strategy,
                "μ₀":        f"{mu0:.0%}",
                "CAGR":      _pct(m.get("cagr")),
                "Sharpe":    _f2(m.get("annualized_sharpe")),
                "Max DD":    _pct(m.get("max_drawdown")),
                "CVaR₁₀":   _pct(m.get("realized_cvar_10")),
                "Total Ret": _pct(m.get("total_return")),
            })

    if spy_nav is not None and not spy_nav.empty and rows:
        # Add SPY row once
        m_spy = compute_metrics(spy_nav.loc[spy_nav.index >= nav_series[rows[0]["Strategy"]].index[0]])
        rows.append({
            "Strategy": "SPY (benchmark)", "Cadence": "—", "Mode": "—", "μ₀": "—",
            "CAGR": _pct(m_spy.get("cagr")), "Sharpe": _f2(m_spy.get("annualized_sharpe")),
            "Max DD": _pct(m_spy.get("max_drawdown")), "CVaR₁₀": "—",
            "Total Ret": _pct(m_spy.get("total_return")),
        })

    summary_df = pd.DataFrame(rows)

    # ── markdown ──────────────────────────────────────────────────────────────
    md_lines = [
        f"# Track A — Backtest Report",
        f"*Generated {today} · Period: {config['track_a']['backtest_start']} → {today}*",
        f"*Capital: €{config['track_a']['initial_capital_eur']:,.0f} + €{config['track_a']['new_capital_per_period_eur']:,.0f}/period new capital*",
        "",
        "## Summary",
        "",
        summary_df.to_markdown(index=False) if not summary_df.empty else "*No results.*",
        "",
        "---",
        "",
        "## Notes",
        "",
        "- **A1 (Full Rebalance):** MILP-CVaR optimizer with full buy/sell allowed each period. "
        "Proportional TC (0.45%) included in objective; fixed TC (€3.90/trade) deducted post-hoc.",
        "- **A2 (Capital Deployment):** Existing positions held unchanged; new quarterly capital "
        "deployed into new stocks only. No selling.",
        f"- **F-Score threshold:** {config['track_a']['fscore']['threshold']} (Piotroski 2000). "
        "Threshold auto-lowered if fewer than "
        f"{config['track_a']['fscore']['min_stocks']} stocks pass.",
        f"- **Return model:** MVN, {config['track_a']['returns']['lookback_days']}-day lookback, "
        f"{config['track_a']['returns']['n_simulations']} simulations.",
        f"- **μ₀ sweep:** {config['track_a']['mu0_sweep_annual']}",
        "",
    ]

    # ── per-cadence detailed tables ───────────────────────────────────────────
    for cadence in config["track_a"]["cadences"]:
        md_lines += [f"## {cadence.capitalize()} cadence — period-by-period", ""]
        for (c, mu0), df in all_results.items():
            if c != cadence or df.empty:
                continue
            md_lines += [f"### μ₀ = {mu0:.0%}", ""]
            display_cols = ["date", "nav_a1", "nav_a2", "a1_return_net", "a2_return_net",
                             "n_a1_positions", "n_eligible", "a1_status"]
            present_cols = [col for col in display_cols if col in df.columns]
            md_lines += [df[present_cols].to_markdown(index=False), ""]

    report_path = _OUTPUT_DIR / f"backtest_{today}.md"
    report_path.write_text("\n".join(md_lines), encoding="utf-8")
    logger.info("Report saved to %s", report_path)

    # ── charts ────────────────────────────────────────────────────────────────
    _save_nav_chart(nav_series, spy_nav, today)
    _save_pareto_chart(all_results, today)

    return report_path


# ── charts ────────────────────────────────────────────────────────────────────

def _save_nav_chart(
    nav_series: dict[str, pd.Series],
    spy_nav: pd.Series | None,
    today,
) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(12, 6))

        # Normalise all series to 100 at start
        for label, nav in nav_series.items():
            if nav.empty:
                continue
            norm = nav / nav.iloc[0] * 100
            style = "--" if "A2" in label else "-"
            ax.plot(norm.index, norm.values, style, label=label, alpha=0.75, linewidth=1.2)

        if spy_nav is not None and not spy_nav.empty:
            # Align spy to first nav start
            starts = [n.index[0] for n in nav_series.values() if not n.empty]
            if starts:
                spy_aligned = spy_nav.loc[spy_nav.index >= min(starts)].dropna()
                if not spy_aligned.empty:
                    spy_norm = spy_aligned / spy_aligned.iloc[0] * 100
                    ax.plot(spy_norm.index, spy_norm.values, "k-", label="SPY", linewidth=2)

        ax.set_title(f"Track A — NAV (indexed to 100 at start) · {today}")
        ax.set_ylabel("NAV (start = 100)")
        ax.legend(fontsize=7, ncol=2)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        path = _OUTPUT_DIR / f"nav_chart_{today}.png"
        fig.savefig(path, dpi=120)
        plt.close(fig)
        logger.info("NAV chart saved to %s", path)
    except Exception as exc:
        logger.warning("NAV chart failed: %s", exc)


def _save_pareto_chart(
    all_results: dict[tuple, pd.DataFrame],
    today,
) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from track_a.src.metrics import build_nav_series, compute_metrics

        fig, ax = plt.subplots(figsize=(9, 6))
        markers = {"quarterly": "o", "yearly": "s"}
        colors  = {"A1": "steelblue", "A2": "coral"}

        for (cadence, mu0), df in all_results.items():
            if df.empty:
                continue
            for mode, col in [("A1", "nav_a1"), ("A2", "nav_a2")]:
                nav = build_nav_series(df, col)
                m = compute_metrics(nav)
                cagr = m.get("cagr", np.nan)
                max_dd = abs(m.get("max_drawdown", np.nan))
                if np.isfinite(cagr) and np.isfinite(max_dd):
                    ax.scatter(max_dd, cagr,
                               marker=markers.get(cadence, "o"),
                               color=colors.get(mode, "grey"),
                               s=60, label=f"{mode} {cadence}", zorder=5)
                    ax.annotate(f"μ₀={mu0:.0%}", (max_dd, cagr), fontsize=7,
                                xytext=(4, 4), textcoords="offset points")

        # Deduplicate legend
        handles, labels = ax.get_legend_handles_labels()
        by_label = dict(zip(labels, handles))
        ax.legend(by_label.values(), by_label.keys(), fontsize=9)

        ax.set_xlabel("Max Drawdown (absolute)")
        ax.set_ylabel("CAGR")
        ax.set_title(f"Track A — Return vs. Risk Pareto Frontier · {today}")
        ax.grid(True, alpha=0.3)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0%}"))
        fig.tight_layout()
        path = _OUTPUT_DIR / f"pareto_{today}.png"
        fig.savefig(path, dpi=120)
        plt.close(fig)
        logger.info("Pareto chart saved to %s", path)
    except Exception as exc:
        logger.warning("Pareto chart failed: %s", exc)


# ── formatting ────────────────────────────────────────────────────────────────

def _pct(val) -> str:
    try:
        return f"{float(val):.1%}" if val is not None and np.isfinite(float(val)) else "—"
    except (TypeError, ValueError):
        return "—"


def _f2(val) -> str:
    try:
        return f"{float(val):.2f}" if val is not None and np.isfinite(float(val)) else "—"
    except (TypeError, ValueError):
        return "—"
