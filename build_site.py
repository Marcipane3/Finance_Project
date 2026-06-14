"""
build_site.py — assemble the cockpit data contract.

Aggregates the latest output of both tracks into a single machine-readable
``web/data/latest.json`` that the static GitHub Pages cockpit reads. Also
maintains ``web/data/track_record.json`` — the realized-performance log that
scores every Track B pick against its benchmark from pick date (BACKLOG NL-4).

Data sources, in priority order, per track:
  1. A JSON sidecar next to the latest report (written by ``*/src/export.py``).
  2. Fallback: parse the latest markdown report on disk.

This means the cockpit renders real data today (markdown parse) and keeps
working unchanged once the pipelines emit sidecars.

The site is **public**; this file deliberately writes **no holdings, share
counts, or € position values**. Personal positions live only in the browser
(localStorage). See docs/DECISIONS.md (2026-06-14 cockpit entry).

Usage:
    uv run python build_site.py            # regenerate web/data/latest.json
    uv run python build_site.py --no-fx    # skip live FX fetch (offline/CI)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path

logger = logging.getLogger("build_site")

ROOT = Path(__file__).parent
WEB_DATA = ROOT / "web" / "data"
TRACK_B_REPORTS = ROOT / "track_b" / "output" / "reports"
TRACK_B_ALERTS = ROOT / "track_b" / "output" / "alerts"
TRACK_A_OUTPUT = ROOT / "track_a" / "output"

# Fallback FX (only used if live fetch is skipped or fails). Refreshed on each
# real run from yfinance; these are coarse June-2026 placeholders.
_FX_FALLBACK = {"usd_eur": 0.92, "gbp_eur": 1.17, "dkk_eur": 0.134, "jpy_eur": 0.0059}


# ── public entry point ──────────────────────────────────────────────────────

def build(fetch_fx: bool = True) -> dict:
    """Build the cockpit payload and write it to web/data/latest.json."""
    WEB_DATA.mkdir(parents=True, exist_ok=True)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "currency": "EUR",
        "fx": _fx_rates(fetch_fx),
        "track_b": _build_track_b(),
        "track_a": _build_track_a(),
    }
    payload["track_record"] = _update_track_record(payload["track_b"])

    out = WEB_DATA / "latest.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Wrote %s", out)
    return payload


# ── Track B ─────────────────────────────────────────────────────────────────

def _build_track_b() -> dict | None:
    sidecar = _latest_file(TRACK_B_REPORTS, "*_report.json")
    if sidecar:
        logger.info("Track B: using sidecar %s", sidecar.name)
        return json.loads(sidecar.read_text(encoding="utf-8"))

    md = _latest_file(TRACK_B_REPORTS, "*_report.md")
    if not md:
        logger.warning("Track B: no report found")
        return None
    logger.info("Track B: parsing markdown %s", md.name)
    return _parse_track_b_md(md)


def _parse_track_b_md(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    as_of = _date_from_name(path.name)

    ticker = _search(r"Monthly Pick:\s*([A-Z0-9.\-]+)", text)
    # line 2: "*2026-05-18 · Western Digital* · Technology / Computer Hardware"
    name = _search(r"\*[\d-]+\s*·\s*([^*]+?)\*", text)
    sector = industry = None
    sect_match = re.search(r"\*\s*·\s*([^/\n]+?)\s*/\s*([^\n*]+)", text)
    if sect_match:
        sector, industry = sect_match.group(1).strip(), sect_match.group(2).strip()

    price = _to_float(_search(r"trading at\s*\*\*\$?([\d,]+\.?\d*)", text))
    action = _search(r"Recommendation:\s*([A-Z]+)", text)
    stop = _to_float(_search(r"stop-loss at\s*([\d.]+)", text))

    leaderboard = _parse_pipeline_table(text)
    # backfill pick fields from leaderboard row 1 when missing
    if leaderboard:
        top = leaderboard[0]
        ticker = ticker or top.get("ticker")
        name = name or top.get("name")

    return {
        "as_of": as_of,
        "pick": {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "industry": industry,
            "price_usd": price,
            "recommendation": {"action": action, "stop_price": stop},
        },
        "leaderboard": leaderboard,
        "report_md": text,
        "stop_loss": _latest_stop_loss(),
    }


def _parse_pipeline_table(text: str) -> list[dict]:
    """Parse the '## Pipeline Summary' markdown table into structured rows."""
    cols = ["rank", "ticker", "name", "score", "forward_pe", "revenue_growth",
            "earnings_growth", "analyst_upside", "rsi_14", "momentum_12_1"]
    rows: list[dict] = []
    in_table = False
    for line in text.splitlines():
        if line.startswith("| # | Ticker"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|") or set(line.replace("|", "").strip()) <= {"-"}:
                if line.startswith("|---") or line.startswith("| ---"):
                    continue
                break  # table ended
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) != len(cols):
                continue
            row = dict(zip(cols, cells))
            rows.append({
                "rank": _to_int(row["rank"]),
                "ticker": row["ticker"],
                "name": row["name"],
                "score": _to_float(row["score"]),
                "forward_pe": _to_float(row["forward_pe"].rstrip("x")),
                "revenue_growth": _pct_to_float(row["revenue_growth"]),
                "earnings_growth": _pct_to_float(row["earnings_growth"]),
                "analyst_upside": _pct_to_float(row["analyst_upside"]),
                "rsi_14": _to_float(row["rsi_14"]),
                "momentum_12_1": _pct_to_float(row["momentum_12_1"]),
            })
    return rows


def _latest_stop_loss() -> dict:
    """Read the most recent daily stop-loss alert sidecar/markdown if present."""
    alert_json = _latest_file(TRACK_B_ALERTS, "*.json")
    if alert_json:
        try:
            return json.loads(alert_json.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"status": "no_position"}


# ── Track A ─────────────────────────────────────────────────────────────────

def _build_track_a() -> dict | None:
    sidecar = _latest_file(TRACK_A_OUTPUT, "live_*.json")
    if sidecar:
        logger.info("Track A: using sidecar %s", sidecar.name)
        return json.loads(sidecar.read_text(encoding="utf-8"))

    md = _latest_file(TRACK_A_OUTPUT, "live_*.md")
    if not md:
        logger.warning("Track A: no live recommendation found")
        return None
    logger.info("Track A: parsing markdown %s", md.name)
    return _parse_track_a_md(md)


def _parse_track_a_md(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    as_of = path.stem.replace("live_", "")

    n_eligible = _to_int(_search(r"Universe:\*\*\s*(\d+)\s*stocks", text))
    threshold = _to_int(_search(r"F-Score >=\s*(\d+)", text))

    def _section_meta(header: str) -> dict:
        m = re.search(
            rf"## {re.escape(header)}.*?\n\*Status:\s*(\w+).*?E\[return\]:\s*([\-\d.]+)%.*?CVaR[^:]*:\s*([\-\d.]+)%.*?TC:\s*€([\d,]+)",
            text, re.DOTALL)
        if not m:
            return {}
        return {
            "status": m.group(1),
            "expected_return": _to_float(m.group(2)) / 100 if m.group(2) else None,
            "cvar": _to_float(m.group(3)) / 100 if m.group(3) else None,
            "tc_eur": _to_float(m.group(4).replace(",", "")),
        }

    a1 = _section_meta("A1 — Full Rebalance")
    a1["positions"] = _parse_a_positions(text, "A1 — Full Rebalance")
    a2 = _section_meta("A2 — Capital Deployment (Buy-Only)")
    a2["positions"] = _parse_a_positions(text, "A2 — Capital Deployment (Buy-Only)")

    return {
        "as_of": as_of,
        "n_eligible": n_eligible,
        "effective_threshold": threshold,
        "a1": a1,
        "a2": a2,
        "report_md": text,
    }


def _parse_a_positions(text: str, header: str) -> list[dict]:
    """Parse 'Ticker | Weight | ≈ EUR' rows under a section header."""
    block = re.split(rf"## {re.escape(header)}", text)
    if len(block) < 2:
        return []
    section = re.split(r"\n## ", block[1])[0]
    rows = []
    for line in section.splitlines():
        m = re.match(r"\|\s*([A-Z0-9.\-]+)\s*\|\s*([\d.]+)%\s*\|\s*€([\d,]+)", line)
        if m:
            rows.append({
                "ticker": m.group(1),
                "weight": _to_float(m.group(2)) / 100,
                "approx_eur": _to_int(m.group(3).replace(",", "")),
            })
    return rows


# ── track record (NL-4) ───────────────────────────────────────────────────────

def _update_track_record(track_b: dict | None) -> list[dict]:
    """Append the current pick to the running record (keyed by ticker+date).

    Realized returns vs benchmark are filled in by a later run / dedicated
    retrospective job; here we just ensure each pick is logged once.
    """
    path = WEB_DATA / "track_record.json"
    record: list[dict] = []
    if path.exists():
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            record = []

    if track_b and track_b.get("pick", {}).get("ticker"):
        pick = track_b["pick"]
        key = (pick["ticker"], track_b.get("as_of"))
        if not any((r.get("ticker"), r.get("pick_date")) == key for r in record):
            record.append({
                "ticker": pick["ticker"],
                "name": pick.get("name"),
                "pick_date": track_b.get("as_of"),
                "entry_price_usd": pick.get("price_usd"),
                "benchmark": "ACWI",
                "status": "open",
                "return_pct": None,
                "benchmark_return_pct": None,
            })

    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return record


# ── FX ────────────────────────────────────────────────────────────────────────

def _fx_rates(fetch: bool) -> dict:
    if not fetch:
        return dict(_FX_FALLBACK)
    try:
        import yfinance as yf
        pairs = {"usd_eur": "EUR=X", "gbp_eur": "GBPEUR=X",
                 "dkk_eur": "DKKEUR=X", "jpy_eur": "JPYEUR=X"}
        out = {}
        for key, sym in pairs.items():
            hist = yf.Ticker(sym).history(period="5d")
            if not hist.empty:
                rate = float(hist["Close"].iloc[-1])
                # EUR=X is USD per EUR; invert to get EUR per USD
                out[key] = (1 / rate) if key == "usd_eur" else rate
        return {**_FX_FALLBACK, **out}
    except Exception as e:  # noqa: BLE001
        logger.warning("FX fetch failed (%s); using fallback", e)
        return dict(_FX_FALLBACK)


# ── small utilities ─────────────────────────────────────────────────────────

def _latest_file(directory: Path, pattern: str) -> Path | None:
    if not directory.exists():
        return None
    files = sorted(directory.glob(pattern))
    return files[-1] if files else None


def _date_from_name(name: str) -> str:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
    return m.group(1) if m else str(date.today())


def _search(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1).strip() if m else None


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _to_int(val) -> int | None:
    f = _to_float(val)
    return int(f) if f is not None else None


def _pct_to_float(val) -> float | None:
    if val is None:
        return None
    f = _to_float(str(val).rstrip("%"))
    return f / 100 if f is not None else None


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the cockpit data contract")
    ap.add_argument("--no-fx", action="store_true", help="skip live FX fetch")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()
    logging.basicConfig(level=args.log_level, format="%(levelname)s %(name)s: %(message)s")
    build(fetch_fx=not args.no_fx)


if __name__ == "__main__":
    main()
