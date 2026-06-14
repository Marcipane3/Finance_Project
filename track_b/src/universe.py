"""
Universe loader for Track B.

Scrapes index constituents from Wikipedia for the five target indices.
Returns a deduplicated DataFrame[ticker, name, index].
Results are cached to parquet; cache is reused if fresher than CACHE_TTL_DAYS.
"""

import io
import logging
import re
import time
from pathlib import Path

import pandas as pd
from curl_cffi import requests  # browser-fingerprint impersonation bypasses bot blocks

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).parent.parent / "data" / "cache" / "universe.parquet"
_CACHE_TTL_DAYS = 7


def load_universe(config: dict, force_refresh: bool = False) -> pd.DataFrame:
    """Return DataFrame[ticker, name, index] for all enabled indices.

    Reads from cache if < CACHE_TTL_DAYS old; re-scrapes otherwise.
    """
    if not force_refresh and _cache_is_fresh():
        logger.info("Universe: loading from cache (%s)", _CACHE_PATH)
        return pd.read_parquet(_CACHE_PATH)

    uni_cfg = config["track_b"]["universe"]
    scrapers = [
        ("SP500",     uni_cfg.get("sp500",     True), _scrape_sp500),
        ("STOXX600",  uni_cfg.get("stoxx600",  True), _scrape_stoxx600),
        ("NIKKEI225", uni_cfg.get("nikkei225", True), _scrape_nikkei225),
        ("FTSE100",   uni_cfg.get("ftse100",   True), _scrape_ftse100),
        ("ASX200",    uni_cfg.get("asx200",    True), _scrape_asx200),
    ]

    frames: list[pd.DataFrame] = []
    for index_name, enabled, fn in scrapers:
        if not enabled:
            logger.info("Universe: %s disabled — skipping", index_name)
            continue
        try:
            df = fn()
            df["index"] = index_name
            frames.append(df)
            logger.info("Universe: %s — %d names scraped", index_name, len(df))
        except Exception as exc:
            logger.warning("Universe: %s failed (%s) — skipping", index_name, exc)
        # Wikipedia rate-limits rapid sequential requests
        time.sleep(1.5)

    if not frames:
        raise RuntimeError("Universe: all scrapers failed; nothing to return.")

    universe = _dedup(pd.concat(frames, ignore_index=True))
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    universe.to_parquet(_CACHE_PATH, index=False)
    logger.info("Universe: %d unique tickers written to %s", len(universe), _CACHE_PATH)
    return universe


# ── helpers ──────────────────────────────────────────────────────────────────

def _cache_is_fresh() -> bool:
    if not _CACHE_PATH.exists():
        return False
    age_days = (time.time() - _CACHE_PATH.stat().st_mtime) / 86400
    return age_days < _CACHE_TTL_DAYS


def _dedup(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)
    df = df.drop_duplicates(subset="ticker", keep="first").reset_index(drop=True)
    if (dropped := before - len(df)):
        logger.info("Universe: dropped %d cross-index duplicates (kept first)", dropped)
    return df


def _fetch(url: str, retries: int = 3) -> io.StringIO:
    for attempt in range(retries):
        r = requests.get(url, impersonate="chrome", timeout=30)
        if r.status_code in (429, 403) and attempt < retries - 1:
            wait = 15 * (2 ** attempt)  # 15s, 30s, ...
            logger.warning("Rate limited by %s — waiting %ds (attempt %d/%d)", url, wait, attempt + 1, retries)
            time.sleep(wait)
            continue
        r.raise_for_status()
        return io.StringIO(r.text)
    r.raise_for_status()  # final attempt exhausted
    return io.StringIO(r.text)  # unreachable but satisfies type checker


def _col_map(tbl: pd.DataFrame) -> dict[str, str]:
    """Map lowercased column names to actual column names for case-insensitive lookup."""
    return {str(c).lower(): str(c) for c in tbl.columns}


# ── per-index scrapers ────────────────────────────────────────────────────────

def _scrape_sp500() -> pd.DataFrame:
    df = pd.read_html(_fetch("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"))[0]
    # Wikipedia uses "." in class-share tickers (BRK.B, BF.B); yfinance expects "-"
    tickers = df["Symbol"].str.strip().str.replace(".", "-", regex=False)
    return pd.DataFrame({"ticker": tickers, "name": df["Security"].str.strip()})


# Country and exchange → yfinance suffix for STOXX 600 home markets
_STOXX_COUNTRY_SUFFIX: dict[str, str] = {
    "Austria":        ".VI",
    "Belgium":        ".BR",
    "Czech Republic": ".PR",
    "Denmark":        ".CO",
    "Finland":        ".HE",
    "France":         ".PA",
    "Germany":        ".DE",
    "Greece":         ".AT",
    "Hungary":        ".BD",
    "Ireland":        ".IR",
    "Italy":          ".MI",
    "Luxembourg":     ".LU",
    "Netherlands":    ".AS",
    "Norway":         ".OL",
    "Poland":         ".WA",
    "Portugal":       ".LS",
    "Spain":          ".MC",
    "Sweden":         ".ST",
    "Switzerland":    ".SW",
    "United Kingdom": ".L",
}

_STOXX_EXCHANGE_SUFFIX: dict[str, str] = {
    "xetra":                  ".DE",
    "euronext paris":         ".PA",
    "euronext amsterdam":     ".AS",
    "euronext brussels":      ".BR",
    "euronext lisbon":        ".LS",
    "london stock exchange":  ".L",
    "lse":                    ".L",
    "six swiss exchange":     ".SW",
    "swiss exchange":         ".SW",
    "borsa italiana":         ".MI",
    "bolsas y mercados":      ".MC",
    "bmex":                   ".MC",
    "nasdaq stockholm":       ".ST",
    "nasdaq helsinki":        ".HE",
    "oslo bors":              ".OL",
    "oslo børs":              ".OL",
    "wiener börse":           ".VI",
    "nasdaq copenhagen":      ".CO",
    "gpw":                    ".WA",
    "prague stock exchange":  ".PR",
    "budapest stock exchange": ".BD",
    "athens stock exchange":  ".AT",
}


def _clean_stoxx_ticker(ticker: str, country: str = "", exchange: str = "") -> str:
    """Normalise a STOXX 600 ticker to yfinance-compatible format.

    1. Replace class-share spaces with hyphens (NOVO B → NOVO-B).
    2. Strip trailing dots from Wikipedia formatting quirks.
    3. If the ticker already contains a dot, assume it has a suffix — leave it.
    4. Look up the exchange suffix via country first, then exchange name.
    """
    t = ticker.strip().replace(" ", "-").rstrip(".")
    if not t or t.lower() in ("nan", "-", ""):
        return ""
    if "." in t:
        return t  # already has an exchange suffix
    suffix = (
        _STOXX_COUNTRY_SUFFIX.get(country.strip())
        or _STOXX_EXCHANGE_SUFFIX.get(exchange.strip().lower())
        or ""
    )
    return t + suffix


def _scrape_stoxx600() -> pd.DataFrame:
    """Scrape STOXX 600 constituents from Wikipedia.

    Captures the Country (and optionally Exchange) columns to build
    yfinance-compatible tickers with the correct exchange suffix.
    When the Wikipedia table doesn't include a Country column the ticker
    is returned as-is (bare local code) and will likely fail yfinance lookup.
    """
    rows: list[dict] = []
    any_country = False

    for tbl in pd.read_html(_fetch("https://en.wikipedia.org/wiki/STOXX_Europe_600")):
        cm = _col_map(tbl)
        ticker_col   = cm.get("ticker") or cm.get("symbol")
        name_col     = cm.get("company") or cm.get("name") or cm.get("security")
        country_col  = cm.get("country") or cm.get("nation") or cm.get("home market") or cm.get("home country")
        exchange_col = cm.get("exchange") or cm.get("stock exchange") or cm.get("listing exchange")

        if ticker_col is None or name_col is None:
            continue

        if country_col is not None:
            any_country = True

        for _, row in tbl.iterrows():
            raw_t = str(row[ticker_col]).strip()
            n     = str(row[name_col]).strip()
            if not raw_t or raw_t.lower() in ("nan", "ticker", "symbol", "-", ""):
                continue
            country  = str(row[country_col]).strip()  if country_col  else ""
            exchange = str(row[exchange_col]).strip() if exchange_col else ""
            t = _clean_stoxx_ticker(raw_t, country, exchange)
            if t:
                rows.append({"ticker": t, "name": n})

    if not rows:
        raise ValueError(
            "no usable ticker table found (Wikipedia page may not list all constituents)"
        )

    result = pd.DataFrame(rows).drop_duplicates(subset="ticker").reset_index(drop=True)

    if any_country:
        suffixed = result["ticker"].str.contains(r"\.[A-Z]", regex=True).sum()
        logger.info(
            "STOXX600: %d names scraped, %d with exchange suffix applied",
            len(result), suffixed,
        )
    else:
        logger.warning(
            "STOXX600: %d names scraped — Wikipedia table has no Country column; "
            "tickers lack exchange suffixes and many yfinance lookups will fail.",
            len(result),
        )
    return result


def _scrape_nikkei225() -> pd.DataFrame:
    """Parse Nikkei 225 constituents from Wikipedia.

    The article lists companies in <ul>/<li> elements (not <table>), so
    pd.read_html() cannot be used. Each entry contains a 4-digit TSE code
    in the pattern "(TYO: 6857)" which is extracted via BeautifulSoup + regex.
    Tickers are suffixed with .T for yfinance compatibility (e.g. 6857.T).
    """
    from bs4 import BeautifulSoup

    html = _fetch("https://en.wikipedia.org/wiki/Nikkei_225").read()
    soup = BeautifulSoup(html, "html.parser")

    rows: list[dict] = []
    seen: set[str] = set()

    for li in soup.find_all("li"):
        text = li.get_text()
        # Pattern: "Company Name (TYO: 6857)" — TSE codes are 4–5 digit numbers
        match = re.search(r'\bTYO\s*:\s*(\d{4,5})\b', text)
        if not match:
            continue
        code = match.group(1)
        if code in seen:
            continue
        seen.add(code)
        # Company name: strip exchange notation, take text before first "("
        name = text.split("(")[0].strip().rstrip(".,; ")
        rows.append({"ticker": f"{code}.T", "name": name})

    if len(rows) < 180:
        raise ValueError(
            f"Nikkei225: only {len(rows)} entries scraped — "
            "page structure may have changed; expected ≥180"
        )

    result = pd.DataFrame(rows).reset_index(drop=True)
    logger.info("Nikkei225: %d tickers scraped from Wikipedia", len(result))
    return result


def _scrape_ftse100() -> pd.DataFrame:
    for tbl in pd.read_html(_fetch("https://en.wikipedia.org/wiki/FTSE_100_Index")):
        cm = _col_map(tbl)
        ticker_col = cm.get("ticker") or cm.get("epic") or cm.get("symbol")
        name_col = cm.get("company") or cm.get("name")
        if ticker_col is None or name_col is None:
            continue
        if len(tbl) < 90:
            continue
        tickers = tbl[ticker_col].str.strip() + ".L"
        names = tbl[name_col].str.strip()
        return pd.DataFrame({"ticker": tickers.values, "name": names.values})

    raise ValueError(
        "could not find constituent table (expected ≥90 rows with Ticker/EPIC column)"
    )


def _scrape_asx200() -> pd.DataFrame:
    for tbl in pd.read_html(_fetch("https://en.wikipedia.org/wiki/S%26P/ASX_200")):
        cm = _col_map(tbl)
        code_col = cm.get("code") or cm.get("ticker") or cm.get("symbol")
        name_col = cm.get("company") or cm.get("name")
        if code_col is None or name_col is None:
            continue
        if len(tbl) < 150:
            continue
        tickers = tbl[code_col].str.strip() + ".AX"
        names = tbl[name_col].str.strip()
        return pd.DataFrame({"ticker": tickers.values, "name": names.values})

    raise ValueError(
        "could not find constituent table (expected ≥150 rows with Code column)"
    )
