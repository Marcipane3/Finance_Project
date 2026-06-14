"""
Deep-dive ranker for Track B.

Takes ~50 pre-filter candidates, enriches each with technical signals
(computed from closes) and fundamental/analyst signals (from yfinance Ticker.info),
then returns the top-N ranked by a weighted composite score.

The output DataFrame carries all raw signal values so the thesis writer
has full context — composite_score is used only for ordering.

Signals where lower raw value = better (forward_pe, realized_vol_30d,
analyst_rating, short_ratio) are inverted before percentile-ranking.
Missing values are filled with the set median.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_DEEPDIVE_CACHE_DIR = Path(__file__).parent.parent / "data" / "cache" / "deepdive"
_DEEPDIVE_CACHE_TTL_DAYS = 1

# signals where lower raw value = better; negated before percentile ranking
_INVERTED = {"forward_pe", "realized_vol_30d", "analyst_rating", "short_ratio"}

# if ALL of these are NaN the fetch failed (bad ticker / rate-limited) — don't cache
_KEY_FIELDS = {"forward_pe", "revenue_growth", "earnings_growth", "profit_margin", "analyst_upside"}

_FUNDAMENTAL_COLS = (
    "forward_pe", "revenue_growth", "earnings_growth", "profit_margin",
    "analyst_upside", "analyst_rating", "short_ratio",
    "market_cap", "currency", "sector", "industry", "current_price",
)
_TECHNICAL_COLS = ("rsi_14", "price_vs_52w_high", "price_vs_ma50", "realized_vol_30d")


def run_ranker(
    candidates: pd.DataFrame,
    closes: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """Return top-N deep-dive candidates sorted descending by composite_score.

    Parameters
    ----------
    candidates : DataFrame from run_prefilter() — top-50
    closes     : wide DataFrame (Date × ticker) from fetch_prices()
    config     : parsed config.yaml

    Returns
    -------
    DataFrame with all candidate columns plus technical, fundamental,
    analyst, and metadata signals, plus composite_score.
    """
    dd_cfg = config["track_b"]["deep_dive"]
    weights: dict[str, float] = dd_cfg["weights"]
    top_n: int = dd_cfg["top_n"]

    tickers = candidates["ticker"].tolist()

    # ── technical signals (vectorised, free) ─────────────────────────────────
    technical = _compute_technical(closes, tickers)
    df = candidates.merge(technical, on="ticker", how="left")
    logger.info("Ranker: technical signals computed for %d/%d tickers", technical["ticker"].notna().sum(), len(tickers))

    # ── fundamental signals (per-ticker fetch, cached) ────────────────────────
    _DEEPDIVE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fundamentals = _fetch_fundamentals(tickers)
    df = df.merge(fundamentals, on="ticker", how="left")

    # ── median fill for scoring columns ──────────────────────────────────────
    score_cols = [c for c in weights if weights[c] > 0]
    for col in score_cols:
        if col not in df.columns:
            continue
        n_missing = df[col].isna().sum()
        if n_missing:
            median = df[col].median()
            df[col] = df[col].fillna(median)
            logger.info("Ranker: filled %d NaN in %s with median %.3f", n_missing, col, median)

    # ── composite score ───────────────────────────────────────────────────────
    df["composite_score"] = _composite_score(df, weights)

    # deduplicate cross-listings before selecting top-N
    before_dedup = len(df)
    df = _dedup_cross_listings(df)
    if len(df) < before_dedup:
        logger.info("Ranker: removed %d cross-listing duplicate(s)", before_dedup - len(df))

    result = (
        df.nlargest(top_n, "composite_score")
        .drop(columns=["prefilter_score"], errors="ignore")
        .reset_index(drop=True)
    )
    logger.info("Ranker: returning %d candidates (top %d of %d)", len(result), top_n, len(df))
    return result


# ── technical signals ─────────────────────────────────────────────────────────

def _compute_technical(closes: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    rows = []
    for ticker in tickers:
        if ticker not in closes.columns:
            rows.append({"ticker": ticker, **{c: float("nan") for c in _TECHNICAL_COLS}})
            continue
        prices = closes[ticker].dropna()
        rows.append({
            "ticker":             ticker,
            "rsi_14":             _rsi(prices),
            "price_vs_52w_high":  _price_vs_52w_high(prices),
            "price_vs_ma50":      _price_vs_ma50(prices),
            "realized_vol_30d":   _realized_vol(prices),
        })
    return pd.DataFrame(rows)


def _rsi(prices: pd.Series, window: int = 14) -> float:
    if len(prices) < window + 1:
        return float("nan")
    delta = prices.diff().dropna()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    # Wilder smoothing via EWM
    avg_gain = gain.ewm(alpha=1 / window, adjust=False).mean().iloc[-1]
    avg_loss = loss.ewm(alpha=1 / window, adjust=False).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    return float(100 - 100 / (1 + avg_gain / avg_loss))


def _price_vs_52w_high(prices: pd.Series) -> float:
    if len(prices) < 2:
        return float("nan")
    high = prices.tail(252).max() if len(prices) >= 252 else prices.max()
    return float(prices.iloc[-1] / high) if high > 0 else float("nan")


def _price_vs_ma50(prices: pd.Series) -> float:
    if len(prices) < 50:
        return float("nan")
    ma50 = prices.tail(50).mean()
    return float(prices.iloc[-1] / ma50) if ma50 > 0 else float("nan")


def _realized_vol(prices: pd.Series, window: int = 30) -> float:
    if len(prices) < window + 1:
        return float("nan")
    log_ret = np.log(prices / prices.shift(1)).dropna().tail(window)
    return float(log_ret.std() * np.sqrt(252))


# ── fundamental / analyst signals ─────────────────────────────────────────────

def _fetch_fundamentals(tickers: list[str]) -> pd.DataFrame:
    stale = [t for t in tickers if not _deepdive_is_fresh(t)]
    logger.info("Ranker fundamentals: %d cached, %d to fetch", len(tickers) - len(stale), len(stale))

    if stale:
        _fetch_and_cache(stale)

    return _load_fundamentals_from_cache(tickers)


def _fetch_and_cache(tickers: list[str]) -> None:
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_fetch_one_fundamental, t): t for t in tickers}
        done = 0
        cached = 0
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                logger.debug("Ranker: %s info fetch error (%s)", ticker, exc)
                result = {col: float("nan") for col in _FUNDAMENTAL_COLS}
                result["ticker"] = ticker
                for meta in ("currency", "sector", "industry"):
                    result[meta] = ""

            # skip caching if all key financial fields are NaN — bad ticker or rate-limit;
            # a missing cache file forces a fresh attempt next run
            if _all_key_fields_nan(result):
                logger.debug("Ranker: %s — all key fields NaN, skipping cache", ticker)
            else:
                pd.DataFrame([result]).to_parquet(_deepdive_cache_path(ticker))
                cached += 1

            done += 1
            if done % 10 == 0:
                logger.info("Ranker: %d/%d fundamentals fetched (%d cached)", done, len(tickers), cached)
    logger.info("Ranker: %d/%d fundamentals cached", cached, len(tickers))


def _fetch_one_fundamental(ticker: str) -> dict:
    last_exc: Exception | None = None
    info: dict = {}
    for attempt in range(3):
        try:
            if attempt > 0:
                wait = 2 ** attempt  # 2s, 4s
                logger.debug("Ranker: %s retry %d/3 in %ds", ticker, attempt + 1, wait)
                time.sleep(wait)
            info = yf.Ticker(ticker).info
            break
        except Exception as exc:
            last_exc = exc
            if attempt == 2:
                raise last_exc  # exhausted retries — let _fetch_and_cache handle it

    time.sleep(0.5)  # per-call rate limiting

    price = (
        info.get("currentPrice")
        or info.get("regularMarketPrice")
        or float("nan")
    )
    target = info.get("targetMeanPrice", float("nan"))
    if price and pd.notna(price) and price > 0 and pd.notna(target):
        analyst_upside = float(target / price - 1)
    else:
        analyst_upside = float("nan")

    return {
        "ticker":          ticker,
        "forward_pe":      _safe_float(info.get("forwardPE")),
        "revenue_growth":  _safe_float(info.get("revenueGrowth")),
        "earnings_growth": _safe_float(info.get("earningsGrowth")),
        "profit_margin":   _safe_float(info.get("profitMargins")),
        "analyst_upside":  analyst_upside,
        "analyst_rating":  _safe_float(info.get("recommendationMean")),
        "short_ratio":     _safe_float(info.get("shortRatio")),
        # metadata — not scored, used by thesis writer
        "market_cap":    _safe_float(info.get("marketCap")),
        "currency":      str(info.get("currency", "")),
        "sector":        str(info.get("sector", "")),
        "industry":      str(info.get("industry", "")),
        "current_price": _safe_float(price),
    }


def _safe_float(val) -> float:
    try:
        f = float(val)
        return f if np.isfinite(f) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _all_key_fields_nan(result: dict) -> bool:
    """Return True when every key financial field is NaN — indicates a failed fetch."""
    return all(
        not np.isfinite(float(result.get(f, float("nan"))))
        for f in _KEY_FIELDS
    )


def _load_fundamentals_from_cache(tickers: list[str]) -> pd.DataFrame:
    rows = []
    for ticker in tickers:
        path = _deepdive_cache_path(ticker)
        row = {"ticker": ticker}
        if path.exists():
            try:
                cached = pd.read_parquet(path)
                for col in _FUNDAMENTAL_COLS:
                    val = cached[col].iloc[0] if col in cached.columns else float("nan")
                    row[col] = val
            except Exception:
                for col in _FUNDAMENTAL_COLS:
                    row[col] = float("nan") if col not in ("currency", "sector", "industry") else ""
        else:
            for col in _FUNDAMENTAL_COLS:
                row[col] = float("nan") if col not in ("currency", "sector", "industry") else ""
        rows.append(row)
    return pd.DataFrame(rows)


# ── cache helpers ─────────────────────────────────────────────────────────────

def _deepdive_cache_path(ticker: str) -> Path:
    safe = ticker.replace("/", "_").replace("\\", "_").replace(":", "_")
    return _DEEPDIVE_CACHE_DIR / f"{safe}.parquet"


def _deepdive_is_fresh(ticker: str) -> bool:
    path = _deepdive_cache_path(ticker)
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) / 86400 < _DEEPDIVE_CACHE_TTL_DAYS


# ── cross-listing deduplication ───────────────────────────────────────────────

def _dedup_cross_listings(df: pd.DataFrame) -> pd.DataFrame:
    """Keep the highest-scoring entry when the same company appears multiple times.

    Two passes:
    1. Base-ticker pass — strips exchange suffix (e.g. NEM.AX → NEM). Catches the
       same stock dual-listed on two exchanges.
    2. Name-normalisation pass — strips share-class designations like "(Class A)".
       Catches economically equivalent share classes (GOOGL vs GOOG).

    df must be sorted descending by composite_score before calling; keep="first"
    retains the higher scorer when a duplicate is found.
    """
    result = df.copy().sort_values("composite_score", ascending=False)

    # Pass 1: base-ticker dedup
    # Capture everything before the first dot-separated exchange suffix (1–3 uppercase letters).
    result["_base"] = result["ticker"].str.extract(
        r'^([A-Z0-9][A-Z0-9-]*)(?:\.[A-Z]{1,3})?$', expand=False
    ).fillna(result["ticker"])
    result = result.drop_duplicates(subset=["_base"], keep="first").drop(columns=["_base"])

    # Pass 2: name-normalisation dedup (share-class variants)
    if "name" in result.columns:
        norm = (
            result["name"].fillna("")
            .str.lower()
            .str.replace(r'\s*\(class [a-z0-9]+\)', '', regex=True)
            .str.replace(
                r'\b(inc|corp|ltd|plc|co|holdings|group|limited|sa|ag|nv|ab|asa)\b\.?',
                '', regex=True,
            )
            .str.replace(r'\s+', ' ', regex=True)
            .str.strip()
        )
        result["_name_norm"] = norm
        result = result.drop_duplicates(subset=["_name_norm"], keep="first").drop(columns=["_name_norm"])

    return result.reset_index(drop=True)


# ── composite score ───────────────────────────────────────────────────────────

def _composite_score(df: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Percentile-rank each signal (negating inverted ones), return weighted average."""
    active = {col: w for col, w in weights.items() if w > 0}
    total_w = sum(active.values())
    score = pd.Series(0.0, index=df.index)
    for col, w in active.items():
        if col not in df.columns:
            logger.warning("Ranker: weight defined for %r but column missing — skipping", col)
            continue
        series = -df[col] if col in _INVERTED else df[col]
        score += series.rank(pct=True, na_option="bottom") * w
    return score / total_w
