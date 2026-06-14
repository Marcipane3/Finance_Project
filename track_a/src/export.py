"""JSON sidecar export for Track A (BACKLOG NL-5).

Writes ``live_{date}.json`` next to the live-recommendation markdown so
``build_site.py`` consumes structured data instead of parsing markdown. Shape
matches what ``build_site._build_track_a`` expects from a sidecar.

The € figures here are model allocations on the *configured* sleeve size, not
real account balances.
"""

from __future__ import annotations

import json
import math
from pathlib import Path


def build_sidecar(rec, report_md: str) -> dict:
    return {
        "as_of": str(rec.as_of),
        "n_eligible": rec.n_eligible,
        "effective_threshold": rec.effective_threshold,
        "a1": {
            "status": rec.a1_status,
            "expected_return": _f(rec.a1_expected_return),
            "cvar": _f(rec.a1_cvar),
            "tc_eur": _f(rec.a1_tc_estimate_eur),
            "positions": [
                {"ticker": p["ticker"], "weight": _f(p["weight"]), "approx_eur": p["approx_eur"]}
                for p in rec.a1_buy
            ],
        },
        "a2": {
            "status": rec.a2_status,
            "expected_return": _f(rec.a2_combined_expected_return),
            "cvar": _f(rec.a2_combined_cvar),
            "tc_eur": _f(rec.a2_tc_estimate_eur),
            "positions": [
                {"ticker": p["ticker"], "weight": _f(p["weight_combined"]), "approx_eur": p["approx_eur"]}
                for p in rec.a2_new_positions
            ],
        },
        "report_md": report_md,
    }


def write_sidecar(report_path: Path, rec, report_md: str) -> Path:
    """Write the sidecar next to the markdown report; return its path."""
    sidecar = report_path.with_suffix(".json")
    sidecar.write_text(
        json.dumps(build_sidecar(rec, report_md), indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    return sidecar


def _f(val) -> float | None:
    try:
        f = float(val)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None
