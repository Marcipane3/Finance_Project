#!/usr/bin/env python
"""
Track B — daily stop-loss check.

Reads the current holding from holdings.csv, fetches the latest closing
price from yfinance, and writes a dated alert file.

Exit codes:
    0 — position is safe, or no active position
    1 — stop-loss BREACHED (position should be exited)
    2 — price unavailable (check ticker / market hours)

Usage:
    uv run python track_b/daily_check.py
    uv run python track_b/daily_check.py --holdings path/to/holdings.csv

Cron example (runs every weekday at 18:00 CET):
    0 18 * * 1-5 cd /path/to/Finance_Project && uv run python track_b/daily_check.py
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from track_b.src.report import load_config
from track_b.src.stopwatch import check_stop_loss, format_alert, save_alert

_EXIT_SAFE    = 0
_EXIT_BREACH  = 1
_EXIT_NO_DATA = 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Track B daily stop-loss check")
    parser.add_argument(
        "--holdings",
        default=None,
        metavar="PATH",
        help="Path to holdings.csv (default: track_b/holdings.csv)",
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Path to config.yaml (default: project root)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Print alert to stdout only, do not write alert file",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config = load_config(Path(args.config) if args.config else None)
    holdings_path = Path(args.holdings) if args.holdings else None

    status = check_stop_loss(config, holdings_path)
    alert_md = format_alert(status)

    print(alert_md)

    if not args.no_save:
        save_alert(status)

    s = status["status"]
    if s == "breached":
        sys.exit(_EXIT_BREACH)
    elif s == "price_unavailable":
        sys.exit(_EXIT_NO_DATA)
    else:
        sys.exit(_EXIT_SAFE)


if __name__ == "__main__":
    main()
