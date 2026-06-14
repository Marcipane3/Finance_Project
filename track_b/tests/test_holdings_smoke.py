"""
Smoke tests for holdings.py.

Tests all decision branches (INITIATE, KEEP, ROTATE, stop-loss triggered)
using a synthetic closes DataFrame and temporary CSV files.

Run:  pytest track_b/tests/test_holdings_smoke.py -v
"""

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from track_b.src.holdings import (
    format_recommendation,
    get_recommendation,
    load_holdings,
)

# ── fixtures ──────────────────────────────────────────────────────────────────

CONFIG = {"track_b": {"stop_loss_pct": 0.10}}

PICK_AVGO = pd.Series({
    "ticker": "AVGO", "name": "Broadcom", "composite_score": 0.87,
})
PICK_NVDA = pd.Series({
    "ticker": "NVDA", "name": "NVIDIA", "composite_score": 0.83,
})

RANKED = pd.DataFrame([
    {"ticker": "AVGO", "composite_score": 0.87},
    {"ticker": "NVDA", "composite_score": 0.83},
    {"ticker": "AAPL", "composite_score": 0.75},
])

CLOSES = pd.DataFrame(
    {
        "AVGO": [1700.0, 1750.0, 1820.0],
        "NVDA": [900.0, 920.0, 950.0],
        "AAPL": [180.0, 182.0, 185.0],
    },
    index=pd.date_range("2026-03-01", periods=3),
)


def _write_holdings(rows: list[dict], tmp_dir: Path) -> Path:
    path = tmp_dir / "holdings.csv"
    cols = ["ticker", "shares", "entry_price", "entry_date", "current_stop_price", "status"]
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False)
    return path


# ── tests ─────────────────────────────────────────────────────────────────────

class TestLoadHoldings:
    def test_creates_empty_file_if_missing(self, tmp_path):
        path = tmp_path / "holdings.csv"
        df = load_holdings(path)
        assert df.empty
        assert path.exists()

    def test_reads_existing_file(self, tmp_path):
        path = _write_holdings(
            [{"ticker": "AVGO", "shares": 1, "entry_price": 1700,
              "entry_date": "2026-04-01", "current_stop_price": 1530, "status": "held"}],
            tmp_path,
        )
        df = load_holdings(path)
        assert len(df) == 1
        assert df.iloc[0]["ticker"] == "AVGO"


class TestGetRecommendation:
    def test_initiate_when_no_holdings(self, tmp_path):
        path = _write_holdings([], tmp_path)
        rec = get_recommendation(PICK_AVGO, RANKED, CLOSES, CONFIG, path)
        assert rec["action"] == "INITIATE"
        assert rec["current_holding"] is None
        assert rec["stop_triggered"] is False

    def test_initiate_when_all_sold(self, tmp_path):
        path = _write_holdings(
            [{"ticker": "TSLA", "shares": 1, "entry_price": 200,
              "entry_date": "2026-02-01", "current_stop_price": 180, "status": "sold"}],
            tmp_path,
        )
        rec = get_recommendation(PICK_AVGO, RANKED, CLOSES, CONFIG, path)
        assert rec["action"] == "INITIATE"

    def test_keep_same_ticker(self, tmp_path):
        path = _write_holdings(
            [{"ticker": "AVGO", "shares": 1, "entry_price": 1700,
              "entry_date": "2026-04-01", "current_stop_price": 1530, "status": "held"}],
            tmp_path,
        )
        rec = get_recommendation(PICK_AVGO, RANKED, CLOSES, CONFIG, path)
        assert rec["action"] == "KEEP"
        assert rec["stop_triggered"] is False

    def test_rotate_different_ticker(self, tmp_path):
        path = _write_holdings(
            [{"ticker": "NVDA", "shares": 1, "entry_price": 900,
              "entry_date": "2026-04-01", "current_stop_price": 810, "status": "held"}],
            tmp_path,
        )
        # new pick is AVGO, current is NVDA → ROTATE
        rec = get_recommendation(PICK_AVGO, RANKED, CLOSES, CONFIG, path)
        assert rec["action"] == "ROTATE"
        assert rec["stop_triggered"] is False
        assert "NVDA" in rec["rationale"]
        assert "AVGO" in rec["rationale"]

    def test_stop_loss_triggered(self, tmp_path):
        # NVDA current price = 950, stop = 960 → triggered
        path = _write_holdings(
            [{"ticker": "NVDA", "shares": 2, "entry_price": 1000,
              "entry_date": "2026-03-01", "current_stop_price": 960, "status": "held"}],
            tmp_path,
        )
        rec = get_recommendation(PICK_AVGO, RANKED, CLOSES, CONFIG, path)
        assert rec["action"] == "ROTATE"
        assert rec["stop_triggered"] is True
        assert "STOP-LOSS" in rec["rationale"].upper()

    def test_new_stop_price_computed(self, tmp_path):
        path = _write_holdings([], tmp_path)
        rec = get_recommendation(PICK_AVGO, RANKED, CLOSES, CONFIG, path)
        # AVGO last close = 1820, stop = 1820 * 0.9 = 1638
        assert abs(rec["new_stop_price"] - 1820 * 0.90) < 1.0

    def test_current_rank_found(self, tmp_path):
        path = _write_holdings(
            [{"ticker": "NVDA", "shares": 1, "entry_price": 900,
              "entry_date": "2026-04-01", "current_stop_price": 810, "status": "held"}],
            tmp_path,
        )
        rec = get_recommendation(PICK_AVGO, RANKED, CLOSES, CONFIG, path)
        # NVDA is rank #2 in RANKED
        assert rec["current_rank"] == 2

    def test_current_rank_none_when_not_in_ranked(self, tmp_path):
        path = _write_holdings(
            [{"ticker": "TSLA", "shares": 1, "entry_price": 200,
              "entry_date": "2026-04-01", "current_stop_price": 180, "status": "held"}],
            tmp_path,
        )
        rec = get_recommendation(PICK_AVGO, RANKED, CLOSES, CONFIG, path)
        assert rec["current_rank"] is None


class TestFormatRecommendation:
    def test_rotate_contains_action(self, tmp_path):
        path = _write_holdings(
            [{"ticker": "NVDA", "shares": 1, "entry_price": 900,
              "entry_date": "2026-04-01", "current_stop_price": 810, "status": "held"}],
            tmp_path,
        )
        rec = get_recommendation(PICK_AVGO, RANKED, CLOSES, CONFIG, path)
        md = format_recommendation(rec)
        assert "ROTATE" in md
        assert "AVGO" in md
        assert "stop-loss" in md.lower()

    def test_initiate_no_closing_line(self, tmp_path):
        path = _write_holdings([], tmp_path)
        rec = get_recommendation(PICK_AVGO, RANKED, CLOSES, CONFIG, path)
        md = format_recommendation(rec)
        assert "INITIATE" in md
        assert "Closing:" not in md
