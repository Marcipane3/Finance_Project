#!/usr/bin/env python
"""
Track B — monthly pick pipeline CLI.

Usage:
    uv run python track_b/run.py
    uv run python track_b/run.py --force-refresh   # bypass all caches
    uv run python track_b/run.py --config path/to/config.yaml
"""

import argparse
import logging
import sys
from pathlib import Path

# allow `python track_b/run.py` from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from track_b.src.report import load_config, run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Track B monthly pick pipeline")
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass all caches and re-fetch universe, prices, and signals",
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Path to config.yaml (default: project root)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING"],
        help="Logging verbosity (default: INFO)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)

    try:
        report_path = run_pipeline(config, force_refresh=args.force_refresh)
        print(f"\nDone. Report saved to:\n  {report_path}")
    except Exception as exc:
        logging.critical("Pipeline failed: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
