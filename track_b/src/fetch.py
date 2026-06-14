"""
Price fetcher for Track B.

Downloads daily adjusted close + volume from yfinance for a list of tickers.
Caches each ticker to track_b/data/cache/prices/{ticker}.parquet (1-day TTL).
Returns (closes, volumes) as wide DataFrames (index=Date, columns=ticker).
Tickers with no yfinance data are silently absent from the result.
"""

import logging
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_PRICE_CACHE_DIR = Path(__file__).parent.parent / "data" / "cache" / "prices"
_PRICE_CACHE_TTL_DAYS = 1

# Exchange suffixes tried when a European ticker fails in the main batch download.
# Applied in order — first success wins.
_ALT_SUFFIXES = [
    ".MI", ".PA", ".DE", ".L", ".AS", ".SW", ".ST",
    ".CO", ".HE", ".OL", ".VI", ".BR", ".MC", ".IR", ".LS", ".AT",
]
# Populated at runtime: original_ticker → working_suffix.  Persists for the session.
_SUFFIX_REMAP: dict[str, str] = {}


def fetch_prices(
    tickers: list[str],
    lookback_days: int = 504,
    force_refresh: bool = False,
    batch_size: int = 200,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (closes, volumes) as wide DataFrames (index=Date, columns=ticker).

    Fetches up to lookback_days of daily history. Stale or missing cache entries
    are re-downloaded; fresh entries are read from disk. Tickers with no usable
    yfinance data are dropped silently.
    """
    _PRICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)

    stale = [t for t in tickers if force_refresh or not _is_fresh(t)]
    if stale:
        logger.info("Prices: %d tickers to download, %d from cache", len(stale), len(tickers) - len(stale))
        _download_and_cache(stale, start_date, end_date, batch_size)
    else:
        logger.info("Prices: all %d tickers fresh in cache", len(tickers))

    return _load_from_cache(tickers)


# ── cache helpers ─────────────────────────────────────────────────────────────

def _cache_path(ticker: str) -> Path:
    safe = ticker.replace("/", "_").replace("\\", "_").replace(":", "_")
    return _PRICE_CACHE_DIR / f"{safe}.parquet"


def _is_fresh(ticker: str) -> bool:
    path = _cache_path(ticker)
    if not path.exists():
        return False
    age_days = (time.time() - path.stat().st_mtime) / 86400
    return age_days < _PRICE_CACHE_TTL_DAYS


def _load_from_cache(tickers: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    closes, volumes = [], []
    missing = 0
    for ticker in tickers:
        path = _cache_path(ticker)
        if not path.exists():
            missing += 1
            continue
        df = pd.read_parquet(path)
        if df.empty or "Close" not in df.columns:
            missing += 1
            continue
        closes.append(df["Close"].rename(ticker))
        volumes.append(df["Volume"].rename(ticker))

    if missing:
        logger.warning("Prices: %d/%d tickers have no data (STOXX600 suffix mismatches expected)", missing, len(tickers))
    if not closes:
        raise RuntimeError("Prices: no data loaded for any ticker.")

    close_df = pd.concat(closes, axis=1).sort_index()
    vol_df = pd.concat(volumes, axis=1).sort_index()
    logger.info("Prices: loaded %d tickers × %d days", len(close_df.columns), len(close_df))
    return close_df, vol_df


# ── download ──────────────────────────────────────────────────────────────────

def _download_and_cache(
    tickers: list[str],
    start_date: date,
    end_date: date,
    batch_size: int,
) -> None:
    n = len(tickers)
    for i in range(0, n, batch_size):
        batch = tickers[i : i + batch_size]
        logger.info("Prices: downloading batch %d–%d / %d", i + 1, min(i + batch_size, n), n)

        try:
            raw = yf.download(
                batch,
                start=start_date.isoformat(),
                end=end_date.isoformat(),
                auto_adjust=True,
                progress=False,
                threads=True,
            )
        except Exception as exc:
            logger.warning("Prices: batch %d–%d failed (%s) — skipping", i + 1, min(i + batch_size, n), exc)
            continue

        if raw.empty:
            logger.warning("Prices: batch %d–%d returned no data", i + 1, min(i + batch_size, n))
            for ticker in batch:
                pd.DataFrame().to_parquet(_cache_path(ticker))
            continue

        # yfinance returns MultiIndex columns (field, ticker) for both single and multi-ticker
        close_wide = raw["Close"]   # DataFrame: date × ticker
        volume_wide = raw["Volume"] # DataFrame: date × ticker

        saved = 0
        found_in_batch: set[str] = set()
        for ticker in batch:
            if ticker not in close_wide.columns:
                continue  # handled after loop
            df = pd.concat(
                [close_wide[ticker].rename("Close"), volume_wide[ticker].rename("Volume")],
                axis=1,
            ).dropna(how="all")
            if len(df) < 10:
                continue  # handled after loop
            df.to_parquet(_cache_path(ticker))
            found_in_batch.add(ticker)
            saved += 1

        # Retry tickers not found in the main download using alternative exchange suffixes.
        # This resolves STOXX 600 / FTSE / Nikkei tickers that need a different suffix.
        not_found = [t for t in batch if t not in found_in_batch]
        if not_found:
            resolved = _retry_with_alt_suffixes(not_found, start_date, end_date)
            saved += len(resolved)
            for ticker in not_found:
                if ticker not in resolved:
                    pd.DataFrame().to_parquet(_cache_path(ticker))

        logger.info("Prices: batch %d–%d — cached %d/%d tickers", i + 1, min(i + batch_size, n), saved, len(batch))


def _retry_with_alt_suffixes(
    tickers: list[str],
    start_date: date,
    end_date: date,
) -> set[str]:
    """Try alternative exchange suffixes for tickers that returned no data.

    Downloads each failed ticker one at a time with each candidate suffix until a
    response with ≥10 rows is returned. Successful data is cached under the original
    ticker name and the working suffix is recorded in _SUFFIX_REMAP.

    Returns the set of tickers that were successfully resolved.
    """
    resolved: set[str] = set()
    for ticker in tickers:
        base = ticker.rsplit(".", 1)[0] if "." in ticker else ticker
        for suffix in _ALT_SUFFIXES:
            alt = f"{base}{suffix}"
            try:
                raw = yf.download(
                    [alt],
                    start=start_date.isoformat(),
                    end=end_date.isoformat(),
                    auto_adjust=True,
                    progress=False,
                    threads=False,
                )
            except Exception:
                continue
            if raw.empty:
                continue
            try:
                close_wide = raw["Close"]
                volume_wide = raw["Volume"]
            except KeyError:
                continue
            if alt not in close_wide.columns:
                continue
            df = pd.concat(
                [close_wide[alt].rename("Close"), volume_wide[alt].rename("Volume")],
                axis=1,
            ).dropna(how="all")
            if len(df) < 10:
                continue
            df.to_parquet(_cache_path(ticker))
            _SUFFIX_REMAP[ticker] = suffix
            resolved.add(ticker)
            logger.debug("Prices: suffix remap %s → %s (success)", ticker, alt)
            break

    if resolved:
        sample = ", ".join(
            f"{t}→{_SUFFIX_REMAP[t]}" for t in list(resolved)[:4]
        )
        logger.info(
            "Prices: suffix remap resolved %d/%d failed tickers (%s%s)",
            len(resolved), len(tickers),
            sample,
            "…" if len(resolved) > 4 else "",
        )
    return resolved
