"""Tests for stages/prepare_calendar.py — event assembly and date parsing."""

import sys
import os
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.prepare_calendar import _parse_date, run


class TestParseDate:
    def test_iso_with_z_suffix(self):
        result = _parse_date("2026-04-15T14:30:00Z")
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 15
        assert result.hour == 14
        assert result.minute == 30

    def test_iso_without_z_suffix(self):
        result = _parse_date("2026-04-15T14:30:00")
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 15

    def test_date_only(self):
        result = _parse_date("2026-04-15")
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 15
        assert result.hour == 0
        assert result.minute == 0

    def test_space_separated_datetime(self):
        result = _parse_date("2026-04-15 14:30")
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 15
        assert result.hour == 14
        assert result.minute == 30

    def test_space_separated_datetime_with_z(self):
        result = _parse_date("2026-04-15 14:30Z")
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 15
        assert result.hour == 14
        assert result.minute == 30

    def test_empty_string_returns_max(self):
        result = _parse_date("")
        assert result == datetime.max

    def test_none_returns_max(self):
        result = _parse_date(None)
        assert result == datetime.max

    def test_invalid_format_returns_max(self):
        result = _parse_date("not-a-date")
        assert result == datetime.max


class TestPrepareCalendarRun:
    def _make_config(self):
        return {"digest": {"week_ahead": {"count": 5}}}

    def test_merges_holidays(self):
        test_holiday = {"date": "2026-04-20", "event": "Pioneer Day"}
        context = {
            "raw_sources": {
                "holidays": [test_holiday],
                "church_events": [],
                "economic_calendar": [],
                "launches": [],
            }
        }
        result = run(context, self._make_config())
        events = result["calendar"]["events"]
        assert len(events) == 1
        assert events[0]["type"] == "holiday"
        assert events[0]["event"] == test_holiday["event"]
        assert events[0]["date"] == test_holiday["date"]

    def test_merges_church_events(self):
        test_event = {
            "date": "2026-04-05",
            "event": "General Conference",
            "description": "Sunday session",
        }
        context = {
            "raw_sources": {
                "holidays": [],
                "church_events": [test_event],
                "economic_calendar": [],
                "launches": [],
            }
        }
        result = run(context, self._make_config())
        events = result["calendar"]["events"]
        assert len(events) == 1
        assert events[0]["type"] == "church"
        assert events[0]["description"] == test_event["description"]

    def test_merges_economic_events(self):
        test_event = {"date": "2026-04-10", "event": "FOMC Meeting", "impact": "high"}
        context = {
            "raw_sources": {
                "holidays": [],
                "church_events": [],
                "economic_calendar": [test_event],
                "launches": [],
            }
        }
        result = run(context, self._make_config())
        events = result["calendar"]["events"]
        assert len(events) == 1
        assert events[0]["type"] == "economic"
        assert events[0]["impact"] == test_event["impact"]

    def test_merges_launches(self):
        test_launch = {
            "date": "2026-04-15",
            "name": "Starlink Group",
            "mission_description": "LEO deployment",
            "provider": "SpaceX",
        }
        context = {
            "raw_sources": {
                "holidays": [],
                "church_events": [],
                "economic_calendar": [],
                "launches": [test_launch],
            }
        }
        result = run(context, self._make_config())
        events = result["calendar"]["events"]
        assert len(events) == 1
        assert events[0]["type"] == "launch"
        assert events[0]["provider"] == test_launch["provider"]
        assert events[0]["description"] == test_launch["mission_description"]

    def test_sorts_events_chronologically(self):
        holiday = {"date": "2026-04-20", "event": "Late Holiday"}
        church = {"date": "2026-04-05", "event": "Early Conference", "description": ""}
        economic = {"date": "2026-04-10", "event": "Mid Event", "impact": ""}
        context = {
            "raw_sources": {
                "holidays": [holiday],
                "church_events": [church],
                "economic_calendar": [economic],
                "launches": [],
            }
        }
        result = run(context, self._make_config())
        events = result["calendar"]["events"]
        dates = [e["date"] for e in events]
        # Derive expected order from input dates (05, 10, 20)
        expected_dates = sorted([church["date"], economic["date"], holiday["date"]])
        assert dates == expected_dates

    def test_caps_events_at_configured_count(self):
        base_date = "2026-04"
        raw_events = [
            {"date": f"{base_date}-{i:02d}", "event": f"Event {i}"}
            for i in range(1, 15)
        ]
        context = {
            "raw_sources": {
                "holidays": raw_events[:5],
                "church_events": raw_events[5:10],
                "economic_calendar": raw_events[10:],
                "launches": [],
            }
        }
        config = {"digest": {"week_ahead": {"count": 3}}}
        result = run(context, config)
        assert result["calendar"]["count"] == 3
        assert len(result["calendar"]["events"]) == 3

    def test_default_cap_is_5(self):
        base_date = "2026-04"
        raw_events = [
            {"date": f"{base_date}-{i:02d}", "event": f"Event {i}"}
            for i in range(1, 10)
        ]
        context = {
            "raw_sources": {
                "holidays": raw_events,
                "church_events": [],
                "economic_calendar": [],
                "launches": [],
            }
        }
        result = run(context, {})
        assert result["calendar"]["count"] == 5
        assert len(result["calendar"]["events"]) == 5

    def test_empty_raw_sources_produces_empty_calendar(self):
        context = {
            "raw_sources": {
                "holidays": [],
                "church_events": [],
                "economic_calendar": [],
                "launches": [],
            }
        }
        result = run(context, self._make_config())
        assert result["calendar"]["events"] == []
        assert result["calendar"]["count"] == 0

    def test_missing_raw_sources_keys_handled(self):
        context = {"raw_sources": {}}
        result = run(context, self._make_config())
        assert result["calendar"]["events"] == []
        assert result["calendar"]["count"] == 0

    def test_missing_context_raw_sources_handled(self):
        context = {}
        result = run(context, self._make_config())
        assert result["calendar"]["events"] == []
        assert result["calendar"]["count"] == 0

    def test_unparseable_dates_sort_to_end(self):
        valid_event = {"date": "2026-04-10", "event": "Valid Date"}
        invalid_event = {
            "date": "not-a-date",
            "event": "Invalid Date",
            "description": "",
        }
        context = {
            "raw_sources": {
                "holidays": [valid_event],
                "church_events": [invalid_event],
                "economic_calendar": [],
                "launches": [],
            }
        }
        result = run(context, self._make_config())
        events = result["calendar"]["events"]
        assert events[0]["event"] == valid_event["event"]
        assert events[1]["event"] == invalid_event["event"]

    def test_launch_uses_correct_keys(self):
        test_launch = {
            "date": "2026-05-01",
            "name": "Test Launch",
            "mission_description": "Test mission",
            "provider": "TestCo",
        }
        context = {
            "raw_sources": {
                "holidays": [],
                "church_events": [],
                "economic_calendar": [],
                "launches": [test_launch],
            }
        }
        result = run(context, self._make_config())
        launch_event = result["calendar"]["events"][0]
        assert launch_event["date"] == test_launch["date"]
        assert launch_event["event"] == test_launch["name"]
        assert launch_event["description"] == test_launch["mission_description"]
        assert launch_event["provider"] == test_launch["provider"]
