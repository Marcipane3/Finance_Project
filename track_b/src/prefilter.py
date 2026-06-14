"""
Pre-filter for Track B.

Reduces the full universe to top-N candidates using a weighted composite of:
  momentum_12_1 (0.30), momentum_1 (0.20), earnings_surprise (0.20),
  analyst_upgrade_30d (0.15), news_volume_30d (0.15).

Two-stage fetch:
  1. Vectorised momentum on all tickers in closes — free, instant.
  2. Per-ticker earnings/analyst/news for the top-300 momentum survivors —
     threaded, cached 7 days.

Missing signal values are filled with the set median (unknown ≠ bad).
All signals are percentile-ranked before weighting so scale doesn't matter.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_SIGNAL_CACHE_DIR = Path(__file__).parent.parent / "data" / "cache" / "signals"
_SIGNAL_CACHE_TTL_DAYS = 7
_MOMENTUM_SCREEN_N = 300
_FETCH_WORKERS = 10
_SIGNAL_COLS = ("earnings_surprise", "analyst_upgrade_30d", "news_volume_30d")


def run_prefilter(
    universe: pd.DataFrame,
    closes: pd.DataFrame,
    volumes: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """Return top-N candidates sorted descending by composite_score.

    Parameters
    ----------
    universe : DataFrame[ticker, name, index]  from load_universe()
    closes   : wide DataFrame (Date × ticker)  from fetch_prices()
    volumes  : wide DataFrame (Date × ticker)  from fetch_prices()
    config   : parsed config.yaml

    Returns
    -------
    DataFrame[ticker, name, index,
              momentum_12_1, momentum_1,
              earnings_surprise, analyst_upgrade_30d, news_volume_30d,
              composite_score]
    """
    pf_cfg = config["track_b"]["prefilter"]
    weights: dict[str, float] = pf_cfg["weights"]
    top_n: int = pf_cfg["top_n"]

    # ── stage 1: vectorised momentum ─────────────────────────────────────────
    momentum = _compute_momentum(closes)
    df = universe.merge(momentum, on="ticker", how="inner")
    logger.info("Prefilter stage 1: %d tickers with price history", len(df))

    # ── ADV liquidity filter ──────────────────────────────────────────────────
    min_adv = config["track_b"]["universe"].get("min_adv_usd", 0)
    if min_adv > 0 and not volumes.empty:
        avail = [t for t in df["ticker"] if t in volumes.columns and t in closes.columns]
        if avail:
            adv = (volumes[avail].tail(30) * closes[avail].tail(30)).mean()
            illiquid = set(adv[adv < min_adv].index)
            before_n = len(df)
            df = df[~df["ticker"].isin(illiquid)]
            logger.info(
                "Prefilter ADV filter ($%.0fM/day min): removed %d illiquid → %d remain",
                min_adv / 1e6, before_n - len(df), len(df),
            )

    # pre-screen by momentum weight alone to limit expensive per-ticker fetches
    df["_mom_rank"] = (
        df["momentum_12_1"].rank(pct=True, na_option="bottom") * weights["momentum_12_1"]
        + df["momentum_1"].rank(pct=True, na_option="bottom") * weights["momentum_1"]
    )
    screen_n = min(_MOMENTUM_SCREEN_N, len(df))
    screened = df.nlargest(screen_n, "_mom_rank").copy()
    logger.info("Prefilter stage 1: top %d by momentum passed to signal fetch", screen_n)

    # ── stage 2: per-ticker signals (threaded, cached) ────────────────────────
    _SIGNAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    signals = _fetch_signals(screened["ticker"].tolist())
    screened = screened.merge(signals, on="ticker", how="left")

    # fill missing with median — treat unknown as average, not penalised
    for col in _SIGNAL_COLS:
        n_missing = screened[col].isna().sum()
        if n_missing:
            median = screened[col].median()
            screened[col] = screened[col].fillna(median)
            logger.info("Prefilter: filled %d NaN in %s with median %.3f", n_missing, col, median)

    # ── stage 3: composite score ──────────────────────────────────────────────
    screened["composite_score"] = _composite_score(screened, weights)
    result = (
        screened
        .nlargest(top_n, "composite_score")
        .drop(columns=["_mom_rank"])
        .reset_index(drop=True)
    )
    logger.info("Prefilter: %d candidates returned (top %d of %d screened)", len(result), top_n, len(screened))
    return result


# ── momentum ──────────────────────────────────────────────────────────────────

def _compute_momentum(closes: pd.DataFrame) -> pd.DataFrame:
    """Vectorised momentum for all tickers in closes."""
    n = len(closes)
    p_now = closes.iloc[-1]
    p_1m  = closes.iloc[-22]  if n >= 22  else pd.Series(float("nan"), index=closes.columns)
    p_12m = closes.iloc[-253] if n >= 253 else pd.Series(float("nan"), index=closes.columns)

    return pd.DataFrame({
        "ticker":        closes.columns.tolist(),
        "momentum_12_1": (p_1m  / p_12m - 1).tolist(),
        "momentum_1":    (p_now / p_1m  - 1).tolist(),
    })


# ── signal fetch ──────────────────────────────────────────────────────────────

def _fetch_signals(tickers: list[str]) -> pd.DataFrame:
    """Return DataFrame[ticker, earnings_surprise, analyst_upgrade_30d, news_volume_30d]."""
    stale = [t for t in tickers if not _signal_is_fresh(t)]
    logger.info("Signals: %d cached, %d to fetch", len(tickers) - len(stale), len(stale))

    if stale:
        _fetch_and_cache(stale)

    return _load_signals_from_cache(tickers)


def _fetch_and_cache(tickers: list[str]) -> None:
    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
        futures = {pool.submit(_fetch_one, t): t for t in tickers}
        done = 0
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                logger.debug("Signals: %s fetch error (%s)", ticker, exc)
                result = {col: float("nan") for col in _SIGNAL_COLS}
            pd.DataFrame([result]).to_parquet(_signal_cache_path(ticker))
            done += 1
            if done % 50 == 0:
                logger.info("Signals: %d/%d fetched", done, len(tickers))
    logger.info("Signals: %d tickers cached", len(tickers))


def _fetch_one(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    return {
        "earnings_surprise":   _get_earnings_surprise(t),
        "analyst_upgrade_30d": _get_analyst_score(t),
        "news_volume_30d":     _get_news_count(t),
    }


def _get_earnings_surprise(t: yf.Ticker) -> float:
    try:
        earnings = t.get_earnings_dates(limit=12)
        if earnings is None or earnings.empty:
            return float("nan")
        reported = earnings[earnings["Reported EPS"].notna()]
        if reported.empty:
            return float("nan")
        # column name varies: "Surprise(%)", "EPS Surprise (%)", or something with "pct"
        surprise_col = next(
            (c for c in reported.columns
             if "surprise" in c.lower() or "pct" in c.lower()),
            None,
        )
        if surprise_col is not None:
            val = reported.iloc[0][surprise_col]
            if pd.notna(val):
                return float(val)
        # manual fallback: (Reported EPS - Estimated EPS) / |Estimated EPS|
        est_col = next(
            (c for c in reported.columns
             if "estimated" in c.lower() or "estimate" in c.lower()),
            None,
        )
        if est_col is not None and "Reported EPS" in reported.columns:
            row = reported.iloc[0]
            rep = row["Reported EPS"]
            est = row[est_col]
            if pd.notna(rep) and pd.notna(est) and float(est) != 0:
                return float((float(rep) - float(est)) / abs(float(est)))
        return float("nan")
    except Exception:
        return float("nan")


def _get_analyst_score(t: yf.Ticker) -> float:
    """Net analyst upgrades minus downgrades in last 30 days."""
    try:
        recs = t.upgrades_downgrades
        if recs is None or recs.empty:
            return float("nan")
        # date may be the index or a column depending on yfinance version
        if isinstance(recs.index, pd.DatetimeIndex):
            dates = recs.index.tz_localize("UTC") if recs.index.tz is None else recs.index.tz_convert("UTC")
        elif "GradeDate" in recs.columns:
            dates = pd.to_datetime(recs["GradeDate"], utc=True)
        else:
            return float("nan")
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)
        recent = recs[dates >= cutoff]
        if recent.empty:
            return float("nan")
        action_col = next((c for c in recent.columns if c.lower() == "action"), None)
        if action_col is None:
            return float("nan")
        return float((recent[action_col] == "up").sum() - (recent[action_col] == "down").sum())
    except Exception:
        return float("nan")


def _get_news_count(t: yf.Ticker) -> float:
    """Count of news items published in the last 30 days.

    yfinance 1.3+ stores timestamps at item['content']['pubDate'] (ISO string).
    Older versions used item['providerPublishTime'] (unix int). Both handled.
    """
    try:
        news = t.news
        if not news:
            return 0.0
        items = news if isinstance(news, list) else []
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=30)
        cutoff_ts = cutoff.timestamp()
        count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            content = item.get("content", item)
            pub = content.get("pubDate") or content.get("displayTime")
            if pub:
                try:
                    dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                    if dt >= cutoff:
                        count += 1
                except (ValueError, TypeError):
                    pass
            elif isinstance(content.get("providerPublishTime"), (int, float)):
                if content["providerPublishTime"] >= cutoff_ts:
                    count += 1
        return float(count)
    except Exception:
        return 0.0


# ── cache helpers ─────────────────────────────────────────────────────────────

def _signal_cache_path(ticker: str) -> Path:
    safe = ticker.replace("/", "_").replace("\\", "_").replace(":", "_")
    return _SIGNAL_CACHE_DIR / f"{safe}.parquet"


def _signal_is_fresh(ticker: str) -> bool:
    path = _signal_cache_path(ticker)
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) / 86400 < _SIGNAL_CACHE_TTL_DAYS


def _load_signals_from_cache(tickers: list[str]) -> pd.DataFrame:
    rows = []
    for ticker in tickers:
        row: dict = {"ticker": ticker}
        path = _signal_cache_path(ticker)
        if path.exists():
            try:
                cached = pd.read_parquet(path)
                for col in _SIGNAL_COLS:
                    row[col] = float(cached[col].iloc[0]) if col in cached.columns else float("nan")
            except Exception:
                for col in _SIGNAL_COLS:
                    row[col] = float("nan")
        else:
            for col in _SIGNAL_COLS:
                row[col] = float("nan")
        rows.append(row)
    return pd.DataFrame(rows)


# ── composite score ───────────────────────────────────────────────────────────

def _composite_score(df: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Percentile-rank each signal then compute weighted average."""
    total_w = sum(weights.values())
    score = pd.Series(0.0, index=df.index)
    for col, w in weights.items():
        if col not in df.columns:
            logger.warning("Prefilter: signal column %r not found — skipping", col)
            continue
        score += df[col].rank(pct=True, na_option="bottom") * w
    return score / total_w
