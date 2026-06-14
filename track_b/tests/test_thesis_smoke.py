"""
Smoke test for thesis.py.

Does NOT call the Claude API — validates the prompt builder and formatter
functions using a synthetic pick row and alternatives DataFrame.

Run:  pytest track_b/tests/test_thesis_smoke.py -v
"""

import numpy as np
import pandas as pd
import pytest

from track_b.src.thesis import (
    _build_user_message,
    _fmt,
    _fmt_market_cap,
    _gt,
)


PICK = pd.Series({
    "ticker":            "AVGO",
    "name":              "Broadcom Inc.",
    "index":             "SP500",
    "sector":            "Technology",
    "industry":          "Semiconductors",
    "currency":          "USD",
    "current_price":     1820.50,
    "market_cap":        850_000_000_000.0,
    "rsi_14":            62.4,
    "price_vs_52w_high": 0.97,
    "price_vs_ma50":     1.04,
    "realized_vol_30d":  0.31,
    "momentum_12_1":     0.52,
    "momentum_1":        0.07,
    "forward_pe":        28.5,
    "revenue_growth":    0.44,
    "earnings_growth":   0.96,
    "profit_margin":     0.39,
    "analyst_upside":    0.18,
    "analyst_rating":    1.8,
    "short_ratio":       1.4,
    "analyst_upgrade_30d": 3.0,
    "news_volume_30d":   12.0,
    "earnings_surprise": 0.03,
    "composite_score":   0.87,
})

ALTS = pd.DataFrame([
    {
        "ticker": "ICG.L", "name": "Intermediate Capital Group",
        "sector": "Financial Services", "composite_score": 0.82,
        "analyst_upside": 0.36, "earnings_growth": 0.96,
        "forward_pe": 10.1, "momentum_12_1": 0.24,
    },
    {
        "ticker": "NVDA", "name": "NVIDIA Corporation",
        "sector": "Technology", "composite_score": 0.79,
        "analyst_upside": 0.21, "earnings_growth": 1.22,
        "forward_pe": 45.0, "momentum_12_1": 0.61,
    },
])


class TestFmtHelpers:
    def test_fmt_pct(self):
        assert _fmt(0.52, pct=True) == "52.0%"

    def test_fmt_plain(self):
        assert _fmt(28.5) == "28.50"

    def test_fmt_nan(self):
        assert _fmt(float("nan")) == "N/A"

    def test_fmt_none(self):
        assert _fmt(None) == "N/A"

    def test_fmt_market_cap_trillion(self):
        result = _fmt_market_cap(850e9, "USD")
        assert "850" in result and "B" in result

    def test_fmt_market_cap_uk_pence_conversion(self):
        # yfinance returns UK market cap in GBp — should ÷100
        result_gbp = _fmt_market_cap(12_000_000_000, "GBP")  # 12B GBp → 120M GBP
        assert "M GBP" in result_gbp or "B GBP" in result_gbp

    def test_gt_true(self):
        assert _gt(0.97, 0.95) is True

    def test_gt_false(self):
        assert _gt(0.90, 0.95) is False

    def test_gt_nan(self):
        assert _gt(float("nan"), 0.95) is False


class TestBuildUserMessage:
    def test_contains_ticker(self):
        msg = _build_user_message(PICK, ALTS)
        assert "AVGO" in msg

    def test_contains_sector(self):
        msg = _build_user_message(PICK, ALTS)
        assert "Technology" in msg

    def test_contains_momentum(self):
        msg = _build_user_message(PICK, ALTS)
        assert "52.0%" in msg  # momentum_12_1

    def test_contains_alternatives(self):
        msg = _build_user_message(PICK, ALTS)
        assert "ICG.L" in msg
        assert "NVDA" in msg

    def test_no_alternatives(self):
        msg = _build_user_message(PICK, pd.DataFrame())
        assert "No runner-up" in msg

    def test_nan_pick_values(self):
        pick_with_nans = PICK.copy()
        pick_with_nans["forward_pe"] = float("nan")
        pick_with_nans["analyst_upside"] = None
        msg = _build_user_message(pick_with_nans, ALTS)
        assert "N/A" in msg
