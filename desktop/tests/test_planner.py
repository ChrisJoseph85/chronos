"""Planner calendar tests: pure-logic fakes only (no GUI, no network)."""
import datetime

from desktop.app.windows.planner import (
    WEEKDAY_HEADERS,
    build_markers,
    event_day_key,
    month_grid,
    month_range_iso,
    month_title,
    prefill_for_event,
    shift_month,
    sort_agenda,
)


def test_agenda_time_ordering():
    events = [
        {"title": "C", "from": "2026-10-06T15:00:00+00:00", "kind": "task"},
        {"title": "A", "from": "2026-10-06T09:00:00+00:00", "kind": "meeting"},
        {"title": "B", "from": "2026-10-06T12:30:00+00:00", "kind": "reminder"},
    ]
    ordered = sort_agenda(events)
    assert [e["title"] for e in ordered] == ["A", "B", "C"]


def test_markers_multi_event_days():
    events = [
        {"title": "A", "from": "2026-10-06T09:00:00+00:00"},
        {"title": "B", "from": "2026-10-06T12:00:00+00:00"},
        {"title": "C", "from": "2026-10-07T09:00:00+00:00"},
    ]
    markers = build_markers(events)
    assert markers["2026-10-06"] == 2
    assert markers["2026-10-07"] == 1
    assert "2026-10-08" not in markers


def test_month_paging_bounds_year_rollover():
    assert shift_month(2026, 12, 1) == (2027, 1)
    assert shift_month(2027, 1, -1) == (2026, 12)
    assert shift_month(2026, 1, -1) == (2025, 12)
    assert shift_month(2026, 6, 0) == (2026, 6)
    # grid for Dec 2026 spills into Jan 2026-days / Jan 2027
    grid = month_grid(2026, 12)
    flat = [d for week in grid for d in week]
    assert any(d.month == 1 and d.year == 2027 for d in flat)
    assert any(d.month == 12 and d.year == 2026 for d in flat)
    # month fetch range stays inside the viewed month
    start, end = month_range_iso(2026, 12)
    assert start.startswith("2026-12-01T00:00:00")
    assert end.startswith("2026-12-31T23:59:00")
    assert month_title(2026, 10) == "October 2026"


def test_tap_prefill_text():
    ev = {"title": "Dentist", "from": "2026-10-06T09:30:00+00:00", "kind": "meeting"}
    text = prefill_for_event(ev, "2026-10-06")
    assert "Dentist" in text
    assert "2026-10-06" in text
    assert "09:30" in text
    assert text[:1].isupper()  # properly capitalized label


def test_weekday_headers_capitalized():
    assert WEEKDAY_HEADERS == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def test_event_day_key_fallbacks():
    assert event_day_key({"from": "2026-10-06T09:00:00+00:00"}) == "2026-10-06"
    assert event_day_key({"start": "2026-01-02T10:00:00+00:00"}) == "2026-01-02"
    assert event_day_key({}) == ""
    assert isinstance(datetime.date(2026, 10, 6).isoformat(), str)
