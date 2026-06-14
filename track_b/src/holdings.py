"""
Holdings manager for Track B.

Reads the manual holdings.csv, checks the current position against the new
pick, and returns a structured KEEP / ROTATE / INITIATE recommendation.

holdings.csv schema (one row per trade; Marcel updates manually):
    ticker, shares, entry_price, entry_date, current_stop_price, status
    status values: held | stopped | sold

At most one row will have status=held at any time. If none exists, the action
is INITIATE (first pick or re-entry after a stopped position).
"""

import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_HOLDINGS_SCHEMA = {
    "ticker":              str,
    "shares":              float,
    "entry_price":         float,
    "entry_date":          str,
    "current_stop_price":  float,
    "status":              str,
}

_DEFAULT_HOLDINGS_PATH = Path(__file__).parent.parent / "holdings.csv"


def get_recommendation(
    new_pick: pd.Series,
    ranked: pd.DataFrame,
    closes: pd.DataFrame,
    config: dict,
    holdings_path: Path | None = None,
) -> dict:
    """Return a holdings-diff recommendation for the monthly pick.

    Parameters
    ----------
    new_pick      : iloc[0] of run_ranker() output — the top-ranked pick
    ranked        : full run_ranker() output — used to find current holding's rank
    closes        : wide DataFrame (Date × ticker) from fetch_prices()
    config        : parsed config.yaml
    holdings_path : override path to holdings.csv (default: track_b/holdings.csv)

    Returns
    -------
    dict with keys:
        action              — "INITIATE" | "KEEP" | "ROTATE"
        new_ticker          — ticker of the recommended pick
        new_stop_price      — stop-loss price for the new pick (-10% of current)
        current_holding     — dict with current position fields, or None
        stop_triggered      — bool: current position is at or below its stop price
        current_rank        — int | None: rank of current holding in this month's run
        rationale           — human-readable explanation string
    """
    stop_pct: float = config["track_b"]["stop_loss_pct"]
    path = holdings_path or _DEFAULT_HOLDINGS_PATH

    current = _load_active_holding(path)
    new_ticker = str(new_pick.get("ticker", ""))
    new_price = _current_price(new_ticker, closes)
    new_stop = new_price * (1 - stop_pct) if new_price and np.isfinite(new_price) else float("nan")

    result = {
        "action":           None,
        "new_ticker":       new_ticker,
        "new_stop_price":   new_stop,
        "current_holding":  current,
        "stop_triggered":   False,
        "current_rank":     None,
        "rationale":        "",
    }

    if current is None:
        result["action"] = "INITIATE"
        result["rationale"] = (
            f"No active position. Initiating new position in {new_ticker}."
        )
        return result

    # check stop-loss on current holding
    held_ticker = str(current.get("ticker", ""))
    stop_price = _safe_float(current.get("current_stop_price"))
    held_price = _current_price(held_ticker, closes)

    stop_triggered = (
        held_price is not None
        and np.isfinite(held_price)
        and np.isfinite(stop_price)
        and held_price <= stop_price
    )
    result["stop_triggered"] = stop_triggered
    if stop_triggered:
        logger.warning(
            "Holdings: stop-loss TRIGGERED for %s — current %.2f ≤ stop %.2f",
            held_ticker, held_price, stop_price,
        )

    # find where current holding ranks in this month's run
    current_rank = _find_rank(held_ticker, ranked)
    result["current_rank"] = current_rank

    # decision logic
    if stop_triggered:
        result["action"] = "ROTATE"
        result["rationale"] = (
            f"STOP-LOSS TRIGGERED: {held_ticker} current price {_fmt(held_price)} "
            f"≤ stop {_fmt(stop_price)}. "
            f"Rotating into {new_ticker}."
        )
    elif held_ticker == new_ticker:
        result["action"] = "KEEP"
        rank_str = f"still ranks #{current_rank}" if current_rank else "still ranks in top picks"
        result["rationale"] = (
            f"Current holding {held_ticker} is the top-ranked pick this month ({rank_str}). "
            f"No rotation warranted."
        )
    else:
        result["action"] = "ROTATE"
        from_rank = f"(ranked #{current_rank} this month)" if current_rank else "(no longer in top picks)"
        entry_price = _safe_float(current.get("entry_price"))
        pnl_str = ""
        if held_price and np.isfinite(held_price) and np.isfinite(entry_price) and entry_price > 0:
            pnl = (held_price / entry_price - 1) * 100
            pnl_str = f" — P&L vs entry: {pnl:+.1f}%"
        result["rationale"] = (
            f"Rotating out of {held_ticker} {from_rank}{pnl_str} "
            f"into new top pick {new_ticker}."
        )

    return result


def load_holdings(path: Path | None = None) -> pd.DataFrame:
    """Return the full holdings history as a DataFrame.

    Creates an empty holdings file with the correct schema if none exists.
    """
    p = path or _DEFAULT_HOLDINGS_PATH
    if not p.exists():
        logger.info("Holdings: %s not found — creating empty file", p)
        empty = pd.DataFrame(columns=list(_HOLDINGS_SCHEMA.keys()))
        p.parent.mkdir(parents=True, exist_ok=True)
        empty.to_csv(p, index=False)
        return empty
    return pd.read_csv(p, dtype=str)


def format_recommendation(rec: dict) -> str:
    """Return a markdown block summarising the KEEP/ROTATE/INITIATE recommendation."""
    action = rec["action"]
    new_ticker = rec["new_ticker"]
    new_stop = rec.get("new_stop_price", float("nan"))
    current = rec.get("current_holding")

    lines = [
        "## Holdings Diff",
        "",
        f"**Recommendation: {action}**",
        "",
        rec.get("rationale", ""),
        "",
    ]

    if rec.get("stop_triggered"):
        lines += [
            "> **STOP-LOSS TRIGGERED** — current position should already be closed. "
            "Confirm exit before placing new order.",
            "",
        ]

    if action in ("ROTATE", "INITIATE") and current:
        held_ticker = current.get("ticker", "?")
        entry_price = current.get("entry_price", "?")
        entry_date = current.get("entry_date", "?")
        lines += [
            f"**Closing:** {held_ticker} | entry {entry_price} on {entry_date}",
        ]

    stop_str = f"{new_stop:.2f}" if new_stop and np.isfinite(new_stop) else "N/A"
    lines += [
        f"**Entering:** {new_ticker} | stop-loss at {stop_str} (−10% from current)",
        "",
        "_Update holdings.csv after executing the trade._",
    ]

    return "\n".join(lines)


# ── internal helpers ──────────────────────────────────────────────────────────

def _load_active_holding(path: Path) -> dict | None:
    """Return the single held row as a dict, or None if no active position."""
    holdings = load_holdings(path)
    if holdings.empty:
        return None
    held = holdings[holdings["status"].str.strip().str.lower() == "held"]
    if held.empty:
        return None
    if len(held) > 1:
        logger.warning(
            "Holdings: %d rows with status=held — using most recent entry_date",
            len(held),
        )
        held = held.sort_values("entry_date", ascending=False)
    row = held.iloc[0].to_dict()
    # coerce numeric fields
    for field in ("shares", "entry_price", "current_stop_price"):
        row[field] = _safe_float(row.get(field))
    return row


def _current_price(ticker: str, closes: pd.DataFrame) -> float | None:
    if ticker not in closes.columns:
        return None
    series = closes[ticker].dropna()
    if series.empty:
        return None
    return float(series.iloc[-1])


def _find_rank(ticker: str, ranked: pd.DataFrame) -> int | None:
    if "ticker" not in ranked.columns:
        return None
    matches = ranked[ranked["ticker"] == ticker]
    if matches.empty:
        return None
    return int(matches.index[0]) + 1  # 1-based rank


def _safe_float(val) -> float:
    try:
        f = float(val)
        return f if np.isfinite(f) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _fmt(val) -> str:
    try:
        f = float(val)
        return f"{f:.2f}" if np.isfinite(f) else "N/A"
    except (TypeError, ValueError):
        return "N/A"
