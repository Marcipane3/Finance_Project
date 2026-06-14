"""
MVN return model for Track A.

Estimates 5-year rolling sample mean and covariance from daily log returns,
then simulates 5000 terminal return scenarios at the rebalance horizon.

Public API:
    fetch_prices(tickers, start_date, force_refresh) -> pd.DataFrame (closes)
    estimate_mvn(closes, tickers, as_of_date, lookback_days) -> (mu, sigma)
    simulate_scenarios(mu, sigma, horizon_days, n_sims, seed) -> np.ndarray (S×N)
"""

import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent.parent / "data" / "cache" / "prices"
_CACHE_TTL_DAYS = 1


# ── price fetching ────────────────────────────────────────────────────────────

def fetch_prices(
    tickers: list[str],
    start_date: str = "2016-01-01",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Return wide DataFrame of daily adjusted closes (Date × ticker).

    Fetches from yfinance and caches per-ticker parquet with 1-day TTL.
    Tickers with no data are silently omitted from the output columns.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    stale = [t for t in tickers if force_refresh or not _is_fresh(t)]
    if stale:
        logger.info("Prices: fetching %d tickers from %s", len(stale), start_date)
        _fetch_and_cache(stale, start_date)

    frames = {}
    for ticker in tickers:
        path = _cache_path(ticker)
        if path.exists() and path.stat().st_size > 100:
            try:
                frames[ticker] = pd.read_parquet(path)["close"]
            except Exception:
                pass

    if not frames:
        return pd.DataFrame()

    closes = pd.DataFrame(frames)
    closes.index = pd.to_datetime(closes.index)
    closes.sort_index(inplace=True)
    logger.info("Prices: loaded %d tickers × %d days", len(closes.columns), len(closes))
    return closes


def _fetch_and_cache(tickers: list[str], start_date: str) -> None:
    chunk_size = 50
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i: i + chunk_size]
        try:
            raw = yf.download(
                chunk,
                start=start_date,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if raw.empty:
                continue
            # yfinance multi-ticker: columns are (field, ticker)
            close_df = raw["Close"] if "Close" in raw else raw.get("close", raw)
            if isinstance(close_df, pd.Series):
                close_df = close_df.to_frame(name=chunk[0])
            for ticker in chunk:
                if ticker in close_df.columns:
                    series = close_df[ticker].dropna()
                    if len(series) >= 20:
                        pd.DataFrame({"close": series}).to_parquet(_cache_path(ticker))
        except Exception as exc:
            logger.debug("Prices: chunk %d fetch error (%s)", i // chunk_size, exc)
        time.sleep(0.5)


# ── MVN estimation ────────────────────────────────────────────────────────────

def estimate_mvn(
    closes: pd.DataFrame,
    tickers: list[str],
    as_of_date: pd.Timestamp,
    lookback_days: int = 1260,
) -> tuple[np.ndarray, np.ndarray]:
    """Estimate daily sample mean vector and covariance matrix from lookback window.

    Parameters
    ----------
    closes       : wide DataFrame (Date × ticker)
    tickers      : list of tickers to include
    as_of_date   : upper bound for the lookback window
    lookback_days: number of trading days to look back (default 1260 ≈ 5 years)

    Returns
    -------
    (mu_daily, sigma_daily) — (N,) and (N×N) arrays; N = len(tickers)
    Missing tickers filled with cross-sectional median.
    """
    avail = [t for t in tickers if t in closes.columns]
    if not avail:
        n = len(tickers)
        return np.zeros(n), np.eye(n) * 0.0004  # ~2% daily vol fallback

    prices = closes.loc[closes.index <= as_of_date, avail].copy()
    prices = prices.tail(lookback_days + 1)

    log_ret = np.log(prices / prices.shift(1)).iloc[1:]

    # Drop columns with too many NaNs (< 80% coverage)
    coverage = log_ret.notna().mean()
    good_cols = coverage[coverage >= 0.80].index.tolist()
    if len(good_cols) < 2:
        n = len(tickers)
        return np.zeros(n), np.eye(n) * 0.0004

    log_ret_clean = log_ret[good_cols].fillna(log_ret[good_cols].median())

    mu_good    = log_ret_clean.mean().values
    sigma_good = log_ret_clean.cov().values

    # Map back to full tickers list; fill missing with median
    ticker_to_idx = {t: i for i, t in enumerate(good_cols)}
    n = len(tickers)
    mu = np.full(n, np.median(mu_good))
    sigma = np.eye(n) * np.median(np.diag(sigma_good))

    good_positions = [i for i, t in enumerate(tickers) if t in ticker_to_idx]
    good_sources   = [ticker_to_idx[t] for t in tickers if t in ticker_to_idx]

    if good_positions:
        mu[good_positions] = mu_good[good_sources]
        for ip, is_ in zip(good_positions, good_sources):
            sigma[ip, ip] = sigma_good[is_, is_]
        if len(good_positions) > 1:
            gp = np.array(good_positions)
            gs = np.array(good_sources)
            sigma[np.ix_(gp, gp)] = sigma_good[np.ix_(gs, gs)]

    sigma = _nearest_positive_definite(sigma)
    return mu, sigma


# ── scenario simulation ───────────────────────────────────────────────────────

def simulate_scenarios(
    mu: np.ndarray,
    sigma: np.ndarray,
    horizon_days: int,
    n_sims: int = 5000,
    seed: int | None = None,
) -> np.ndarray:
    """Simulate terminal portfolio returns under MVN.

    Scales daily mu/sigma to the horizon and draws n_sims samples.

    Returns
    -------
    (n_sims × N) array of terminal fractional returns (not log returns).
    """
    mu_h    = mu * horizon_days
    sigma_h = sigma * horizon_days

    rng = np.random.default_rng(seed)
    log_returns = rng.multivariate_normal(mu_h, sigma_h, size=n_sims)
    return np.exp(log_returns) - 1   # convert log returns to simple returns


# ── helpers ───────────────────────────────────────────────────────────────────

def _cache_path(ticker: str) -> Path:
    safe = ticker.replace("/", "_").replace("\\", "_").replace(":", "_")
    return _CACHE_DIR / f"{safe}.parquet"


def _is_fresh(ticker: str) -> bool:
    path = _cache_path(ticker)
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) / 86400 < _CACHE_TTL_DAYS


def _nearest_positive_definite(A: np.ndarray) -> np.ndarray:
    """Compute the nearest positive-definite matrix via eigenvalue clamping."""
    B = (A + A.T) / 2
    eigvals, eigvecs = np.linalg.eigh(B)
    eigvals = np.maximum(eigvals, 1e-10)
    return eigvecs @ np.diag(eigvals) @ eigvecs.T
