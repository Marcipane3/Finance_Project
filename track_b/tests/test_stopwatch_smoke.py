"""
Smoke tests for stopwatch.py.

No network calls — _fetch_price is monkeypatched throughout.

Run:  pytest track_b/tests/test_stopwatch_smoke.py -v
"""

import json
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


def _no_watch(tmp_dir: Path) -> Path:
    """A watch_path that does not exist — isolates tests from the repo's real
    web/data/watch.json so the holdings.csv path is the only target source."""
    return tmp_dir / "no_watch.json"


def _write_watch(data: dict, tmp_dir: Path) -> Path:
    path = tmp_dir / "watch.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ── check_stop_loss ───────────────────────────────────────────────────────────

class TestCheckStopLoss:
    def test_no_position(self, tmp_path):
        path = _write_holdings([], tmp_path)
        s = check_stop_loss(CONFIG, path, watch_path=_no_watch(tmp_path))
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
        s = check_stop_loss(CONFIG, path, watch_path=_no_watch(tmp_path))
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


# ── watch.json fallback (CI path) ─────────────────────────────────────────────

class TestWatchFallback:
    def test_watch_used_when_no_holdings(self, tmp_path, monkeypatch):
        monkeypatch.setattr("track_b.src.stopwatch._fetch_price", lambda t: 470.0)
        holdings = _write_holdings([], tmp_path)  # empty → no local target
        watch = _write_watch(
            {"ticker": "WDC", "entry_price": 450.0, "stop_price": 405.0,
             "pick_date": "2026-05-18"},
            tmp_path,
        )
        s = check_stop_loss(CONFIG, holdings, watch_path=watch)
        assert s["status"] == "safe"
        assert s["ticker"] == "WDC"
        assert s["source"] == "watch"
        assert s["shares"] is None              # never any € / share data from watch
        assert s["entry_date"] == "2026-05-18"  # pick_date maps to entry_date

    def test_watch_breach_detected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("track_b.src.stopwatch._fetch_price", lambda t: 400.0)
        watch = _write_watch(
            {"ticker": "WDC", "entry_price": 450.0, "stop_price": 405.0,
             "pick_date": "2026-05-18"},
            tmp_path,
        )
        s = check_stop_loss(CONFIG, _write_holdings([], tmp_path), watch_path=watch)
        assert s["status"] == "breached"
        assert s["source"] == "watch"

    def test_local_holdings_take_priority(self, tmp_path, monkeypatch):
        monkeypatch.setattr("track_b.src.stopwatch._fetch_price", lambda t: 950.0)
        holdings = _write_holdings(
            [{"ticker": "NVDA", "shares": 2, "entry_price": 900,
              "entry_date": "2026-04-01", "current_stop_price": 810, "status": "held"}],
            tmp_path,
        )
        watch = _write_watch({"ticker": "WDC", "entry_price": 450.0,
                              "stop_price": 405.0, "pick_date": "2026-05-18"}, tmp_path)
        s = check_stop_loss(CONFIG, holdings, watch_path=watch)
        assert s["ticker"] == "NVDA"        # local wins
        assert s["source"] == "holdings"
        assert s["shares"] == pytest.approx(2.0)

    def test_alert_flags_watch_source(self, tmp_path, monkeypatch):
        monkeypatch.setattr("track_b.src.stopwatch._fetch_price", lambda t: 470.0)
        watch = _write_watch({"ticker": "WDC", "entry_price": 450.0,
                              "stop_price": 405.0, "pick_date": "2026-05-18"}, tmp_path)
        s = check_stop_loss(CONFIG, _write_holdings([], tmp_path), watch_path=watch)
        md = format_alert(s)
        assert "watch.json" in md


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
