"""
Annual fundamental statement fetcher for Track A.

Fetches and caches balance_sheet, income_stmt, cashflow per ticker from yfinance.
Cache: per-ticker parquet triplet at track_a/data/cache/fundamentals/, 7-day TTL.

Usage:
    statements = fetch_fundamentals(["AAPL", "MSFT"])
    bs = statements["AAPL"]["balance_sheet"]   # DataFrame: line items × fiscal year Timestamps
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent.parent / "data" / "cache" / "fundamentals"
_CACHE_TTL_DAYS = 7
_SHEETS = ("balance_sheet", "income_stmt", "cashflow")
_MAX_WORKERS = 5
_RATE_LIMIT_S = 0.5


def fetch_fundamentals(
    tickers: list[str],
    force_refresh: bool = False,
) -> dict[str, dict[str, pd.DataFrame]]:
    """Return {ticker: {sheet_name: DataFrame}} for all tickers.

    Missing or rate-limited tickers will have empty DataFrames in the result.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    stale = [t for t in tickers if force_refresh or not _is_fresh(t)]
    cached_count = len(tickers) - len(stale)
    logger.info("Fundamentals: %d cached, %d to fetch", cached_count, len(stale))

    if stale:
        _fetch_and_cache(stale)

    return {t: _load_from_cache(t) for t in tickers}


# ── fetch + cache ─────────────────────────────────────────────────────────────

def _fetch_and_cache(tickers: list[str]) -> None:
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_one, t): t for t in tickers}
        done = 0
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                sheets = future.result()
            except Exception as exc:
                logger.debug("Fundamentals: %s fetch error (%s)", ticker, exc)
                sheets = {s: pd.DataFrame() for s in _SHEETS}

            if _any_sheet_has_data(sheets):
                _write_cache(ticker, sheets)
            else:
                logger.debug("Fundamentals: %s — all sheets empty, skipping cache", ticker)

            done += 1
            if done % 20 == 0:
                logger.info("Fundamentals: %d/%d fetched", done, len(tickers))

    logger.info("Fundamentals: fetch complete (%d tickers)", len(tickers))


def _fetch_one(ticker: str) -> dict[str, pd.DataFrame]:
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            if attempt > 0:
                wait = 2 ** attempt
                logger.debug("Fundamentals: %s retry %d in %ds", ticker, attempt + 1, wait)
                time.sleep(wait)
            t = yf.Ticker(ticker)
            sheets = {
                "balance_sheet": t.balance_sheet,
                "income_stmt":   t.income_stmt,
                "cashflow":      t.cashflow,
            }
            time.sleep(_RATE_LIMIT_S)
            return sheets
        except Exception as exc:
            last_exc = exc

    raise last_exc  # type: ignore[misc]


def _any_sheet_has_data(sheets: dict[str, pd.DataFrame]) -> bool:
    return any(isinstance(df, pd.DataFrame) and not df.empty for df in sheets.values())


# ── cache helpers ─────────────────────────────────────────────────────────────

def _cache_path(ticker: str, sheet: str) -> Path:
    safe = ticker.replace("/", "_").replace("\\", "_").replace(":", "_")
    return _CACHE_DIR / f"{safe}_{sheet}.parquet"


def _is_fresh(ticker: str) -> bool:
    paths = [_cache_path(ticker, s) for s in _SHEETS]
    if not all(p.exists() for p in paths):
        return False
    oldest_mtime = min(p.stat().st_mtime for p in paths)
    return (time.time() - oldest_mtime) / 86400 < _CACHE_TTL_DAYS


def _write_cache(ticker: str, sheets: dict[str, pd.DataFrame]) -> None:
    for sheet, df in sheets.items():
        path = _cache_path(ticker, sheet)
        if isinstance(df, pd.DataFrame) and not df.empty:
            df.to_parquet(path)
        else:
            pd.DataFrame().to_parquet(path)


def _load_from_cache(ticker: str) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for sheet in _SHEETS:
        path = _cache_path(ticker, sheet)
        if path.exists():
            try:
                result[sheet] = pd.read_parquet(path)
            except Exception:
                result[sheet] = pd.DataFrame()
        else:
            result[sheet] = pd.DataFrame()
    return result
