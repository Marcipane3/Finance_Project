"""JSON sidecar export for Track B (BACKLOG NL-5).

Writes a machine-readable ``{date}_report.json`` next to each markdown report so
``build_site.py`` consumes structured data directly instead of parsing markdown.
The shape matches what ``build_site._build_track_b`` expects from a sidecar.

Carries research only — no holdings, share counts, or € position values.
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import pandas as pd

# leaderboard column -> ranker DataFrame column
_LEADERBOARD_COLS = {
    "ticker": "ticker",
    "name": "name",
    "score": "composite_score",
    "forward_pe": "forward_pe",
    "revenue_growth": "revenue_growth",
    "earnings_growth": "earnings_growth",
    "analyst_upside": "analyst_upside",
    "rsi_14": "rsi_14",
    "momentum_12_1": "momentum_12_1",
}


def build_sidecar(pick: pd.Series, ranked: pd.DataFrame, rec: dict, report_md: str) -> dict:
    return {
        "as_of": str(date.today()),
        "pick": {
            "ticker": _s(pick.get("ticker")),
            "name": _s(pick.get("name")),
            "sector": _s(pick.get("sector")),
            "industry": _s(pick.get("industry")),
            "price_usd": _f(pick.get("current_price")),
            "recommendation": {
                "action": rec.get("action"),
                "stop_price": _f(rec.get("new_stop_price")),
            },
        },
        "leaderboard": _leaderboard(ranked),
        "report_md": report_md,
    }


def write_sidecar(report_path: Path, pick: pd.Series, ranked: pd.DataFrame,
                  rec: dict, report_md: str) -> Path:
    """Write the sidecar next to the markdown report; return its path."""
    sidecar = report_path.with_suffix(".json")
    data = build_sidecar(pick, ranked, rec, report_md)
    sidecar.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    return sidecar


def _leaderboard(ranked: pd.DataFrame) -> list[dict]:
    rows = []
    for rank, (_, row) in enumerate(ranked.iterrows(), start=1):
        entry = {"rank": rank}
        for out_key, src_col in _LEADERBOARD_COLS.items():
            val = row.get(src_col)
            entry[out_key] = _s(val) if out_key in ("ticker", "name") else _f(val)
        rows.append(entry)
    return rows


def _f(val) -> float | None:
    try:
        f = float(val)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _s(val) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s and s.lower() != "nan" else None
