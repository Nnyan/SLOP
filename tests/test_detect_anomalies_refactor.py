"""Regression tests for the detect_anomalies refactor (step 2.7.d).

`detect_anomalies` previously had cyclomatic complexity 16. The refactor
extracts 6 helpers (`_load_failure_events`, `_group_failure_events`,
`_build_maintenance_index`, `_is_in_maintenance`,
`_describe_typical_time`, `_pattern_for_group`). The orchestrator drops
to ≤ 4.

These tests exercise the cleanly-isolatable helpers — DB-bound
`_load_failure_events` is covered end-to-end by the existing
test_anomaly_detection.py suite.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.health.anomaly import (  # noqa: E402
    _DAY_NAMES,
    _build_maintenance_index,
    _describe_typical_time,
    _group_failure_events,
    _is_in_maintenance,
    _pattern_for_group,
)


# ── _describe_typical_time ─────────────────────────────────────────


def test_describe_neither_returns_empty() -> None:
    assert _describe_typical_time(None, None) == ""


def test_describe_hour_only() -> None:
    assert _describe_typical_time(3, None) == " — often around 03:00"


def test_describe_day_only() -> None:
    assert _describe_typical_time(None, 1) == " — often on Tue"


def test_describe_hour_and_day() -> None:
    assert _describe_typical_time(14, 4) == " — often around 14:00 on Fri"


def test_day_names_match_iso_weekday_indexing() -> None:
    """0=Mon..6=Sun — matches datetime.weekday() return values."""
    assert _DAY_NAMES == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ── _group_failure_events ──────────────────────────────────────────


class _Row(dict):
    """sqlite3.Row stand-in — supports both [key] and ['key'] lookup."""


def test_group_failure_events_buckets_by_app_and_check() -> None:
    rows = [
        _Row(app_key="sonarr", check_name="http", checked_at=100, summary="x"),
        _Row(app_key="sonarr", check_name="http", checked_at=200, summary=""),
        _Row(app_key="sonarr", check_name="db",  checked_at=150, summary="y"),
        _Row(app_key="radarr", check_name="http", checked_at=300, summary=None),
    ]
    out = _group_failure_events(rows)
    assert len(out) == 3
    assert len(out[("sonarr", "http")]) == 2
    assert len(out[("sonarr", "db")]) == 1
    assert len(out[("radarr", "http")]) == 1
    assert out[("sonarr", "http")][0]["timestamp"] == 100
    assert out[("radarr", "http")][0]["summary"] == "", \
        "summary=None must coerce to '' to match downstream expectations"


# ── _build_maintenance_index ───────────────────────────────────────


def test_build_maintenance_index_keys_by_app_and_check() -> None:
    mw_rows = [
        _Row(app_key="sonarr", check_name="http",
             day_of_week=2, hour_start=3, hour_end=5),
        _Row(app_key="sonarr", check_name="http",
             day_of_week=None, hour_start=22, hour_end=-1),
    ]
    mw_index = _build_maintenance_index(mw_rows)
    assert len(mw_index[("sonarr", "http")]) == 2


def test_build_maintenance_index_expands_minus_one_end() -> None:
    """`hour_end == -1` → 2-hour window starting at hour_start."""
    mw_rows = [
        _Row(app_key="x", check_name="y",
             day_of_week=None, hour_start=22, hour_end=-1),
    ]
    mw_index = _build_maintenance_index(mw_rows)
    w = mw_index[("x", "y")][0]
    assert w["h_start"] == 22 and w["h_end"] == 24


# ── _is_in_maintenance ─────────────────────────────────────────────


def test_in_maintenance_returns_false_when_no_window() -> None:
    assert _is_in_maintenance(0, "x", "y", {}) is False


def test_in_maintenance_respects_hour_window() -> None:
    # 2026-05-08 14:00 UTC = a Friday at 14:00 (weekday=4)
    import calendar
    ts = calendar.timegm((2026, 5, 8, 14, 0, 0, 0, 0, 0))
    mw_index = {
        ("a", "b"): [{"day": None, "h_start": 13, "h_end": 15}],
    }
    assert _is_in_maintenance(ts, "a", "b", mw_index) is True
    mw_index = {
        ("a", "b"): [{"day": None, "h_start": 9, "h_end": 12}],
    }
    assert _is_in_maintenance(ts, "a", "b", mw_index) is False


def test_in_maintenance_respects_day_filter() -> None:
    """Day filter excludes events on non-matching days."""
    import calendar
    # 2026-05-08 is Friday (weekday=4)
    ts = calendar.timegm((2026, 5, 8, 14, 0, 0, 0, 0, 0))
    # Match: Friday rule
    mw_index_fri = {
        ("a", "b"): [{"day": 4, "h_start": 13, "h_end": 15}],
    }
    assert _is_in_maintenance(ts, "a", "b", mw_index_fri) is True
    # Mismatch: Monday rule, event is Friday
    mw_index_mon = {
        ("a", "b"): [{"day": 0, "h_start": 13, "h_end": 15}],
    }
    assert _is_in_maintenance(ts, "a", "b", mw_index_mon) is False


# ── _pattern_for_group ─────────────────────────────────────────────


def test_pattern_for_group_returns_none_below_threshold() -> None:
    """Fewer than 3 events → no pattern (need recurrence to be a pattern)."""
    events = [{"timestamp": 100, "summary": ""}, {"timestamp": 200, "summary": ""}]
    out = _pattern_for_group("sonarr", "http", events, {}, 168)
    assert out is None


def test_pattern_for_group_returns_pattern_above_threshold() -> None:
    """3+ events → an AnomalyPattern with the right fields."""
    events = [
        {"timestamp": 100, "summary": ""},
        {"timestamp": 3700, "summary": ""},
        {"timestamp": 7300, "summary": ""},
    ]
    out = _pattern_for_group("sonarr", "http", events, {}, 168)
    assert out is not None
    assert out.app_key == "sonarr"
    assert out.check_name == "http"
    assert out.occurrences == 3
    assert out.first_seen == 100
    assert out.last_seen == 7300
    assert out.is_recurring is False, \
        "3 events alone shouldn't tip is_recurring (need ≥5)"
    assert "http has failed 3 times" in out.description


def test_pattern_for_group_filters_maintenance_events() -> None:
    """An event inside a maintenance window must NOT count toward the 3-event threshold."""
    import calendar
    ts_in = calendar.timegm((2026, 5, 8, 14, 0, 0, 0, 0, 0))  # Friday 14:00 UTC
    ts_out_1 = ts_in + 7 * 86400  # +1 week
    ts_out_2 = ts_in + 14 * 86400
    events = [
        {"timestamp": ts_in,    "summary": ""},  # filtered
        {"timestamp": ts_out_1, "summary": ""},
        {"timestamp": ts_out_2, "summary": ""},
    ]
    mw_index = {
        ("a", "b"): [{"day": 4, "h_start": 13, "h_end": 15}],  # Friday 13–15
    }
    # ts_in is in window → effective count is 2 → below threshold → None
    # But ts_out_1 / ts_out_2 are also Fri 14:00 (a week later still Fri 14)
    # so they too match the window. Adjust: shift the surviving events.
    events = [
        {"timestamp": ts_in,                "summary": ""},  # filtered
        {"timestamp": ts_in + 1 * 86400,    "summary": ""},  # Sat — survives
        {"timestamp": ts_in + 2 * 86400,    "summary": ""},  # Sun — survives
    ]
    out = _pattern_for_group("a", "b", events, mw_index, 168)
    assert out is None, \
        "3 events but 1 in maintenance → 2 effective → below 3-event threshold"
