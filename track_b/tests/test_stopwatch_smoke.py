"""
Smoke tests for stopwatch.py.

No network calls — _fetch_price is monkeypatched throughout.

Run:  pytest track_b/tests/test_stopwatch_smoke.py -v
"""

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from track_b.src.stopwatch import check_stop_loss, format_alert

CONFIG = {"track_b": {"stop_loss_pct": 0.10, "sleeve_eur": 2000.0}}


def _write_holdings(rows: list[dict], tmp_dir: Path) -> Path:
    path = tmp_dir / "holdings.csv"
    cols = ["ticker", "shares", "entry_price", "entry_date", "current_stop_price", "status"]
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False)
    return path


# ── check_stop_loss ───────────────────────────────────────────────────────────

class TestCheckStopLoss:
    def test_no_position(self, tmp_path):
        path = _write_holdings([], tmp_path)
        s = check_stop_loss(CONFIG, path)
        assert s["status"] == "no_position"
        assert s["ticker"] is None

    def test_safe_position(self, tmp_path, monkeypatch):
        monkeypatch.setattr("track_b.src.stopwatch._fetch_price", lambda t: 950.0)
        path = _write_holdings(
            [{"ticker": "NVDA", "shares": 2, "entry_price": 900,
              "entry_date": "2026-04-01", "current_stop_price": 810, "status": "held"}],
            tmp_path,
        )
        s = check_stop_loss(CONFIG, path)
        assert s["status"] == "safe"
        assert s["ticker"] == "NVDA"
        assert abs(s["current_price"] - 950.0) < 0.01
        assert s["pnl_pct"] == pytest.approx(950 / 900 - 1)
        assert s["distance_to_stop"] > 0  # current > stop

    def test_breached_position(self, tmp_path, monkeypatch):
        # current 800 ≤ stop 810 → breached
        monkeypatch.setattr("track_b.src.stopwatch._fetch_price", lambda t: 800.0)
        path = _write_holdings(
            [{"ticker": "NVDA", "shares": 2, "entry_price": 900,
              "entry_date": "2026-04-01", "current_stop_price": 810, "status": "held"}],
            tmp_path,
        )
        s = check_stop_loss(CONFIG, path)
        assert s["status"] == "breached"
        assert s["distance_to_stop"] < 0

    def test_price_at_exact_stop(self, tmp_path, monkeypatch):
        # price == stop → breached (dist == 0)
        monkeypatch.setattr("track_b.src.stopwatch._fetch_price", lambda t: 810.0)
        path = _write_holdings(
            [{"ticker": "NVDA", "shares": 2, "entry_price": 900,
              "entry_date": "2026-04-01", "current_stop_price": 810, "status": "held"}],
            tmp_path,
        )
        s = check_stop_loss(CONFIG, path)
        assert s["status"] == "breached"

    def test_price_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setattr("track_b.src.stopwatch._fetch_price", lambda t: None)
        path = _write_holdings(
            [{"ticker": "FAKE", "shares": 1, "entry_price": 100,
              "entry_date": "2026-04-01", "current_stop_price": 90, "status": "held"}],
            tmp_path,
        )
        s = check_stop_loss(CONFIG, path)
        assert s["status"] == "price_unavailable"

    def test_stopped_position_ignored(self, tmp_path, monkeypatch):
        monkeypatch.setattr("track_b.src.stopwatch._fetch_price", lambda t: 950.0)
        path = _write_holdings(
            [{"ticker": "NVDA", "shares": 2, "entry_price": 900,
              "entry_date": "2026-04-01", "current_stop_price": 810, "status": "stopped"}],
            tmp_path,
        )
        s = check_stop_loss(CONFIG, path)
        assert s["status"] == "no_position"

    def test_pnl_computed_correctly(self, tmp_path, monkeypatch):
        # entry 1000, current 1200 → +20%
        monkeypatch.setattr("track_b.src.stopwatch._fetch_price", lambda t: 1200.0)
        path = _write_holdings(
            [{"ticker": "AAPL", "shares": 1, "entry_price": 1000,
              "entry_date": "2026-03-01", "current_stop_price": 900, "status": "held"}],
            tmp_path,
        )
        s = check_stop_loss(CONFIG, path)
        assert s["pnl_pct"] == pytest.approx(0.20)


# ── format_alert ──────────────────────────────────────────────────────────────

class TestFormatAlert:
    def _safe_status(self):
        return {
            "status": "safe", "ticker": "AVGO", "current_price": 1820.0,
            "stop_price": 1638.0, "entry_price": 1700.0, "entry_date": "2026-04-01",
            "pnl_pct": 0.071, "distance_to_stop": 0.111, "shares": 1.1,
            "sleeve_eur": 2000.0, "date": "2026-05-18",
        }

    def _breached_status(self):
        return {
            "status": "breached", "ticker": "NVDA", "current_price": 800.0,
            "stop_price": 810.0, "entry_price": 900.0, "entry_date": "2026-04-01",
            "pnl_pct": -0.111, "distance_to_stop": -0.012, "shares": 2.0,
            "sleeve_eur": 2000.0, "date": "2026-05-18",
        }

    def test_safe_contains_ticker(self):
        md = format_alert(self._safe_status())
        assert "AVGO" in md
        assert "Safe" in md

    def test_breached_contains_warning(self):
        md = format_alert(self._breached_status())
        assert "BREACHED" in md
        assert "NVDA" in md
        assert "Action required" in md

    def test_no_position_message(self):
        md = format_alert({"status": "no_position", "date": "2026-05-18",
                           "ticker": None, "sleeve_eur": 2000})
        assert "No active position" in md

    def test_price_unavailable_message(self):
        md = format_alert({"status": "price_unavailable", "date": "2026-05-18",
                           "ticker": "FAKE", "sleeve_eur": 2000})
        assert "unavailable" in md.lower()

    def test_pnl_shown(self):
        md = format_alert(self._safe_status())
        assert "+7.1%" in md

    def test_distance_shown(self):
        md = format_alert(self._safe_status())
        assert "+11.1%" in md  # distance_to_stop
