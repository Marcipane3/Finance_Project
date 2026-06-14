"""
Smoke tests for report.py assembler.

Tests _assemble() and the formatting helpers with synthetic data.
Does NOT run the full pipeline (no network, no API).

Run:  pytest track_b/tests/test_report_smoke.py -v
"""

import pandas as pd
import pytest

from track_b.src.report import _assemble, _fmt2, _fmt_pct, _fmt_x, _pipeline_table


PICK = pd.Series({
    "ticker": "AVGO", "name": "Broadcom Inc.",
    "sector": "Technology", "industry": "Semiconductors",
    "composite_score": 0.87,
    "forward_pe": 28.5, "revenue_growth": 0.44, "earnings_growth": 0.96,
    "analyst_upside": 0.18, "rsi_14": 62.4, "momentum_12_1": 0.52,
})

RANKED = pd.DataFrame([
    {"ticker": "AVGO", "name": "Broadcom Inc.", "sector": "Technology",
     "composite_score": 0.87, "forward_pe": 28.5, "revenue_growth": 0.44,
     "earnings_growth": 0.96, "analyst_upside": 0.18, "rsi_14": 62.4, "momentum_12_1": 0.52},
    {"ticker": "NVDA", "name": "NVIDIA Corporation", "sector": "Technology",
     "composite_score": 0.79, "forward_pe": 45.0, "revenue_growth": 0.78,
     "earnings_growth": 1.22, "analyst_upside": 0.21, "rsi_14": 70.1, "momentum_12_1": 0.61},
])

THESIS = "## Company Snapshot\nBroadcom designs semiconductors.\n\n## Bull Case\nStrong AI exposure."

HOLDINGS_MD = "## Holdings Diff\n\n**Recommendation: INITIATE**\n\nNo active position."

STATS = {
    "universe_n": 1269, "prices_n": 950,
    "prefilter_n": 50, "ranker_n": 15, "elapsed_s": 42.3,
}


class TestPipelineTable:
    def test_contains_tickers(self):
        t = _pipeline_table(RANKED)
        assert "AVGO" in t
        assert "NVDA" in t

    def test_rank_numbers(self):
        t = _pipeline_table(RANKED)
        assert "| 1 |" in t
        assert "| 2 |" in t

    def test_pct_formatting(self):
        t = _pipeline_table(RANKED)
        assert "44.0%" in t   # revenue_growth AVGO

    def test_nan_values_show_dash(self):
        ranked_with_nan = RANKED.copy()
        ranked_with_nan.loc[0, "forward_pe"] = float("nan")
        t = _pipeline_table(ranked_with_nan)
        assert "—" in t


class TestAssemble:
    def test_title_contains_ticker(self):
        md = _assemble(PICK, RANKED, THESIS, HOLDINGS_MD, STATS)
        assert "# Track B — Monthly Pick: AVGO" in md

    def test_contains_thesis(self):
        md = _assemble(PICK, RANKED, THESIS, HOLDINGS_MD, STATS)
        assert "## Company Snapshot" in md
        assert "## Bull Case" in md

    def test_contains_holdings_section(self):
        md = _assemble(PICK, RANKED, THESIS, HOLDINGS_MD, STATS)
        assert "## Holdings Diff" in md
        assert "INITIATE" in md

    def test_contains_pipeline_summary(self):
        md = _assemble(PICK, RANKED, THESIS, HOLDINGS_MD, STATS)
        assert "## Pipeline Summary" in md
        assert "1,269" in md   # universe_n formatted with comma

    def test_footer_present(self):
        md = _assemble(PICK, RANKED, THESIS, HOLDINGS_MD, STATS)
        assert "Track B v0.1" in md
        assert "42s" in md   # elapsed rounded


class TestFmtHelpers:
    def test_fmt_pct_normal(self):
        assert _fmt_pct(0.44) == "44.0%"

    def test_fmt_pct_nan(self):
        assert _fmt_pct(float("nan")) == "—"

    def test_fmt_pct_none(self):
        assert _fmt_pct(None) == "—"

    def test_fmt_x_normal(self):
        assert _fmt_x(28.5) == "28.5x"

    def test_fmt2_normal(self):
        assert _fmt2(0.87) == "0.87"
