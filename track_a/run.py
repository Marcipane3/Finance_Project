"""
Track A CLI entry point.

Usage:
    uv run python track_a/run.py --mode backtest
    uv run python track_a/run.py --mode backtest --cadence yearly --mu0 0.10
    uv run python track_a/run.py --mode live --new-capital 3000
    uv run python track_a/run.py --mode smoke --cadence quarterly --mu0 0.05
"""

import argparse
import logging
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))


def _load_config() -> dict:
    with open(_ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_backtest(args) -> None:
    from track_a.src.backtest import run_backtest
    from track_a.src.metrics import compare_strategies

    config = _load_config()
    if args.new_capital is not None:
        config["track_a"]["new_capital_per_period_eur"] = args.new_capital

    cadences = [args.cadence] if args.cadence else config["track_a"]["cadences"]
    mu0_list = [args.mu0] if args.mu0 is not None else config["track_a"]["mu0_sweep_annual"]

    all_results = {}
    for cadence in cadences:
        for mu0 in mu0_list:
            logging.info("=== %s μ₀=%.0f%% ===", cadence, mu0 * 100)
            df = run_backtest(
                cadence=cadence,
                mu0_annual=mu0,
                config=config,
                force_refresh=args.force_refresh,
            )
            all_results[(cadence, mu0)] = df
            cmp = compare_strategies(df)
            print(f"\n{cadence} μ₀={mu0:.0%}")
            print(cmp.to_string(index=False))

    # Generate full report
    from track_a.src.backtest import _load_spy
    from track_a.src.report import generate_report
    spy = _load_spy(config["track_a"]["price_history_start"])
    report_path = generate_report(all_results, config, spy_nav=spy)
    print(f"\nReport saved: {report_path}")


def cmd_smoke(args) -> None:
    """Quick 2-period smoke test to verify the pipeline works end-to-end."""
    import pandas as pd
    from track_a.src.backtest import run_backtest

    config = _load_config()
    # Override: only 2 periods, start late so fewer tickers needed
    config["track_a"]["backtest_start"] = "2024-09-01"
    config["track_a"]["returns"]["n_simulations"] = 500   # faster than 5000 for smoke

    mu0 = args.mu0 if args.mu0 is not None else 0.05
    cadence = args.cadence or "quarterly"
    logging.info("Smoke test: cadence=%s, mu0=%.0f%%", cadence, mu0 * 100)

    df = run_backtest(cadence=cadence, mu0_annual=mu0, config=config)
    print(f"\nSmoke result ({len(df)} periods):")
    print(df[["date", "nav_a1", "nav_a2", "a1_status", "n_a1_positions", "n_eligible"]].to_string(index=False))
    logging.info("Smoke test complete — %d periods", len(df))


def cmd_live(args) -> None:
    from pathlib import Path

    from track_a.src.live import format_recommendation, run_live

    config = _load_config()
    if args.mu0 is not None:
        config["track_a"]["live_mu0_annual"] = args.mu0
    if args.new_capital is not None:
        config["track_a"]["new_capital_per_period_eur"] = args.new_capital

    holdings_path = Path("track_a/holdings.csv") if Path("track_a/holdings.csv").exists() else None
    rec = run_live(config, holdings_path=holdings_path, force_refresh=args.force_refresh)
    md = format_recommendation(rec)
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(md)

    # Save to output
    from datetime import date
    out_dir = Path("track_a/output")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"live_{date.today()}.md"
    out_path.write_text(md, encoding="utf-8")
    print(f"\nSaved to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Track A — Portfolio Optimizer")
    parser.add_argument("--mode",          choices=["backtest", "live", "smoke"], default="smoke")
    parser.add_argument("--cadence",       choices=["quarterly", "yearly"], default=None)
    parser.add_argument("--mu0",           type=float, default=None, help="Annual min return (e.g. 0.10)")
    parser.add_argument("--new-capital",   type=float, default=None, dest="new_capital")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--log-level",     default="INFO")
    args = parser.parse_args()

    _setup_logging(args.log_level)

    if args.mode == "backtest":
        cmd_backtest(args)
    elif args.mode == "live":
        cmd_live(args)
    elif args.mode == "smoke":
        cmd_smoke(args)


if __name__ == "__main__":
    main()
