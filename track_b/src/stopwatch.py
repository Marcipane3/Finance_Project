"""
Daily stop-loss monitor for Track B.

Fetches the latest closing price for the currently held position and
compares it against the stop-loss price in holdings.csv. Returns a
structured status dict and can write a dated alert file.

Intended as a lightweight daily cron — does not run the full pipeline.
Exit code from daily_check.py: 0 = safe (or no position), 1 = breach.
"""

import json
import logging
from datetime import date
from pathlib import Path

import numpy as np
import yfinance as yf

from track_b.src.holdings import load_holdings

logger = logging.getLogger(__name__)

_ALERT_DIR = Path(__file__).parent.parent / "output" / "alerts"
# Non-sensitive public stop-loss trigger emitted by build_site._write_watch().
_WATCH_PATH = Path(__file__).parent.parent.parent / "web" / "data" / "watch.json"


def check_stop_loss(
    config: dict,
    holdings_path: Path | None = None,
    watch_path: Path | None = None,
) -> dict:
    """Return a status dict for the currently held position.

    Resolves the watch target in priority order:
      1. the local ``holdings.csv`` (full detail: shares, entry, stop) — used on
         Marcel's machine, never committed;
      2. the committed non-sensitive ``web/data/watch.json`` (ticker + entry/stop
         only) — the CI fallback so the daily cron isn't a no-op.

    Returns
    -------
    dict with keys:
        status          — "no_position" | "safe" | "breached" | "price_unavailable"
        ticker          — str or None
        current_price   — float or None
        stop_price      — float or None
        entry_price     — float or None
        entry_date      — str or None
        pnl_pct         — float or None   (current_price / entry_price - 1)
        distance_to_stop — float or None  (current_price / stop_price - 1, negative = breached)
        shares          — float or None
        source          — "holdings" | "watch" | None
        sleeve_eur      — float           (from config)
        date            — str             (today)
    """
    sleeve_eur: float = config["track_b"].get("sleeve_eur", 2000.0)

    base = {
        "status":           "no_position",
        "ticker":           None,
        "current_price":    None,
        "stop_price":       None,
        "entry_price":      None,
        "entry_date":       None,
        "pnl_pct":          None,
        "distance_to_stop": None,
        "shares":           None,
        "source":           None,
        "sleeve_eur":       sleeve_eur,
        "date":             str(date.today()),
    }

    target = _load_local_target(holdings_path) or _load_watch_target(watch_path)
    if target is None:
        return base

    ticker = target["ticker"]
    base.update({
        "ticker":      ticker,
        "stop_price":  target["stop_price"],
        "entry_price": target["entry_price"],
        "entry_date":  target["entry_date"],
        "shares":      target["shares"],
        "source":      target["source"],
    })
    entry_price = target["entry_price"]
    stop_price  = target["stop_price"]

    current_price = _fetch_price(ticker)
    if current_price is None:
        base["status"] = "price_unavailable"
        logger.warning("Stopwatch: could not fetch price for %s", ticker)
        return base

    base["current_price"] = current_price

    pnl = (current_price / entry_price - 1) if np.isfinite(entry_price) and entry_price > 0 else None
    dist = (current_price / stop_price - 1) if np.isfinite(stop_price) and stop_price > 0 else None

    base["pnl_pct"]          = pnl
    base["distance_to_stop"] = dist

    breached = (
        dist is not None
        and dist <= 0  # current_price <= stop_price
    )
    base["status"] = "breached" if breached else "safe"

    if breached:
        logger.warning(
            "STOP-LOSS BREACHED: %s current %.2f ≤ stop %.2f (dist %.1f%%)",
            ticker, current_price, stop_price, dist * 100,
        )
    else:
        logger.info(
            "Stopwatch: %s safe — price %.2f, stop %.2f, dist %.1f%%, P&L %+.1f%%",
            ticker, current_price, stop_price,
            dist * 100 if dist is not None else float("nan"),
            pnl * 100 if pnl is not None else float("nan"),
        )

    return base


def save_alert(status: dict, alert_dir: Path | None = None) -> Path:
    """Write a dated markdown alert file. Returns the file path."""
    out_dir = alert_dir or _ALERT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{status['date']}.md"
    path.write_text(format_alert(status), encoding="utf-8")
    logger.info("Alert saved to %s", path)
    return path


def format_alert(status: dict) -> str:
    """Return a human-readable markdown alert string."""
    today = status["date"]
    s = status["status"]

    if s == "no_position":
        return f"# Track B Stop-Loss Check — {today}\n\n**No active position.** Nothing to monitor.\n"

    ticker = status["ticker"]

    if s == "price_unavailable":
        return (
            f"# Track B Stop-Loss Check — {today}\n\n"
            f"⚠️ **Price unavailable for {ticker}**\n\n"
            "yfinance returned no price data. Check market hours or ticker validity.\n"
        )

    price  = status["current_price"]
    stop   = status["stop_price"]
    entry  = status["entry_price"]
    dist   = status["distance_to_stop"]
    pnl    = status["pnl_pct"]
    edate  = status["entry_date"]
    shares = status["shares"]
    sleeve = status["sleeve_eur"]

    price_str = f"{price:.2f}" if price is not None else "N/A"
    stop_str  = f"{stop:.2f}"  if stop  is not None else "N/A"
    entry_str = f"{entry:.2f}" if entry is not None else "N/A"
    dist_str  = f"{dist * 100:+.1f}%" if dist is not None else "N/A"
    pnl_str   = f"{pnl  * 100:+.1f}%" if pnl  is not None else "N/A"

    if s == "breached":
        header = f"# Track B Stop-Loss Check — {today}\n\n🚨 **STOP-LOSS BREACHED: {ticker}**"
        action = "**Action required: exit position, move to cash, wait for next monthly run.**"
    else:
        header = f"# Track B Stop-Loss Check — {today}\n\n✅ **{ticker} — Safe**"
        action = "_No action required._"

    lines = [
        header,
        "",
        action,
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Ticker | {ticker} |",
        f"| Current price | {price_str} |",
        f"| Stop-loss price | {stop_str} |",
        f"| Distance to stop | {dist_str} |",
        f"| P&L vs entry ({entry_str} on {edate}) | {pnl_str} |",
        f"| Shares | {shares if shares is not None else 'N/A'} |",
        f"| Sleeve | ~€{sleeve:,.0f} |",
        "",
        f"*Check run: {today}*",
    ]
    if status.get("source") == "watch":
        lines += [
            "",
            "_Source: public watch.json (pick price as entry proxy; no share/€ data). "
            "Local holdings.csv overrides this when run on your machine._",
        ]
    return "\n".join(lines) + "\n"


# ── target resolution ───────────────────────────────────────────────────────

def _load_local_target(holdings_path: Path | None) -> dict | None:
    """Active position from the local (gitignored) holdings.csv, or None."""
    holdings = load_holdings(holdings_path)
    if holdings.empty:
        return None
    held = holdings[holdings["status"].str.strip().str.lower() == "held"]
    if held.empty:
        return None
    row = held.iloc[0]
    ticker = str(row.get("ticker", "")).strip()
    if not ticker:
        return None
    return {
        "ticker":      ticker,
        "entry_price": _sf(row.get("entry_price")),
        "stop_price":  _sf(row.get("current_stop_price")),
        "shares":      _sf(row.get("shares")),
        "entry_date":  str(row.get("entry_date", "")).strip(),
        "source":      "holdings",
    }


def _load_watch_target(watch_path: Path | None) -> dict | None:
    """Public non-sensitive watch.json target (CI fallback), or None.

    No share count exists in the public file — ``shares`` is therefore None and
    the alert reports % distance/P&L only, never a € value.
    """
    p = watch_path or _WATCH_PATH
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Stopwatch: could not parse watch file %s", p)
        return None
    ticker = str(data.get("ticker", "")).strip()
    if not ticker:
        return None
    return {
        "ticker":      ticker,
        "entry_price": _sf(data.get("entry_price")),
        "stop_price":  _sf(data.get("stop_price")),
        "shares":      None,
        "entry_date":  str(data.get("pick_date", "")).strip(),
        "source":      "watch",
    }


# ── helpers ───────────────────────────────────────────────────────────────────

def _fetch_price(ticker: str) -> float | None:
    """Return the most recent closing price for ticker, or None on failure."""
    try:
        hist = yf.Ticker(ticker).history(period="5d")
        if hist.empty or "Close" not in hist.columns:
            return None
        price = float(hist["Close"].dropna().iloc[-1])
        return price if np.isfinite(price) else None
    except Exception as exc:
        logger.debug("Stopwatch: price fetch failed for %s (%s)", ticker, exc)
        return None


def _sf(val) -> float:
    try:
        f = float(val)
        return f if np.isfinite(f) else float("nan")
    except (TypeError, ValueError):
        return float("nan")
