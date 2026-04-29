"""Tests for sources/ modules."""

import sys
import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sources.holidays import get_upcoming_holidays
from sources.come_follow_me import (
    get_current_lesson,
    get_upcoming_church_events,
    GENERAL_CONFERENCE_DATES,
    SCHEDULE_2026,
)
from sources.economic_calendar import fetch_economic_calendar
from sources.rss_feeds import (
    fetch_rss,
    fetch_rss_with_diagnostics,
    _clean_summary,
    _parse_feed_date,
    _fetch_direct,
    _items_from_parsed_feed,
    _items_from_html_index,
    _state_key,
    _skip_due_to_cooldown,
)


class TestHolidays:
    def test_returns_list_of_dicts(self):
        result = get_upcoming_holidays(days=10)
        assert isinstance(result, list)
        for item in result:
            assert "date" in item
            assert "event" in item

    def test_date_format_is_iso(self):
        result = get_upcoming_holidays(days=365)
        for item in result:
            date.fromisoformat(item["date"])  # should not raise

    def test_empty_window_returns_empty(self):
        result = get_upcoming_holidays(days=0)
        assert isinstance(result, list)

    def test_includes_pioneer_day_when_in_range(self):
        # Pioneer Day is July 24 in Utah
        with patch("sources.holidays.date") as mock_date:
            mock_date.today.return_value = date(2026, 7, 20)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = get_upcoming_holidays(days=10)
            events = [item["event"] for item in result]
            assert any("Pioneer" in e for e in events)


class TestComeFollowMe:
    def test_schedule_has_lessons(self):
        assert len(SCHEDULE_2026) > 0

    def test_lesson_dates_are_valid(self):
        for start_str, end_str, num, reading, title, key_ref in SCHEDULE_2026:
            date.fromisoformat(start_str)
            date.fromisoformat(end_str)
            assert num >= 1

    def test_general_conference_dates_are_valid(self):
        for d in GENERAL_CONFERENCE_DATES:
            assert isinstance(d, date)
            # General Conference is always on a weekend
            assert d.weekday() in (5, 6)  # Saturday or Sunday

    def test_get_current_lesson_returns_dict(self):
        config = {"come_follow_me": {"base_url": "https://example.com"}}
        result = get_current_lesson(config)
        assert isinstance(result, dict)
        assert "reading" in result
        assert "title" in result
        assert "key_scripture" in result

    def test_get_current_lesson_fallback_returns_empty_fields(self):
        config = {"come_follow_me": {"base_url": "https://example.com"}}
        # Patch today to a date outside the schedule range
        with patch("sources.come_follow_me.date") as mock_date:
            mock_date.today.return_value = date(2027, 6, 1)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            mock_date.fromisoformat = date.fromisoformat
            result = get_current_lesson(config)
            assert result["reading"] == ""
            assert result["title"] == "Come, Follow Me"

    def test_get_upcoming_church_events_returns_events_in_range(self):
        # Patch today to be near a General Conference date
        with patch("sources.come_follow_me.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 1)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = get_upcoming_church_events(lookahead_days=10)
            assert len(result) > 0
            for event in result:
                assert "date" in event
                assert "event" in event
                assert "General Conference" in event["event"]

    def test_get_upcoming_church_events_empty_outside_range(self):
        with patch("sources.come_follow_me.date") as mock_date:
            mock_date.today.return_value = date(2026, 6, 1)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = get_upcoming_church_events(lookahead_days=10)
            assert result == []


class TestEconomicCalendar:
    def test_returns_empty_without_api_key(self):
        with patch.dict(os.environ, {"FINNHUB_API_KEY": ""}, clear=False):
            result = fetch_economic_calendar({})
            assert result == []

    @patch("sources.economic_calendar.http_get_json")
    def test_filters_to_us_events(self, mock_get):
        mock_get.return_value = {
            "economicCalendar": [
                {
                    "country": "US",
                    "impact": "high",
                    "event": "Fed Rate Decision",
                    "time": "2026-04-15T14:00:00Z",
                },
                {
                    "country": "UK",
                    "impact": "high",
                    "event": "BOE Rate",
                    "time": "2026-04-15T12:00:00Z",
                },
                {
                    "country": "US",
                    "impact": "low",
                    "event": "Minor Report",
                    "time": "2026-04-15T10:00:00Z",
                },
            ]
        }

        with patch.dict(os.environ, {"FINNHUB_API_KEY": "test-key"}):
            result = fetch_economic_calendar({})

        assert len(result) == 1
        assert result[0]["event"] == "Fed Rate Decision"
        assert result[0]["impact"] == "high"

    @patch("sources.economic_calendar.http_get_json")
    def test_returns_empty_on_error(self, mock_get):
        mock_get.return_value = None
        with patch.dict(os.environ, {"FINNHUB_API_KEY": "test-key"}):
            result = fetch_economic_calendar({})
        assert result == []


class TestRssFeeds:
    def test_clean_summary_strips_html(self):
        html = "<p>Hello <b>world</b></p>"
        result = _clean_summary(html)
        assert "<p>" not in result
        assert "Hello world" in result

    def test_clean_summary_truncates_long_text(self):
        text = "A" * 500
        result = _clean_summary(text)
        assert len(result) <= 400
        assert result.endswith("...")

    def test_clean_summary_collapses_whitespace(self):
        text = "  Hello   world  "
        result = _clean_summary(text)
        assert result == "Hello world"

    def test_parse_feed_date_with_parsed_field(self):
        import time

        entry = MagicMock()
        entry.get.side_effect = lambda k, d=None: {
            "published_parsed": time.struct_time((2026, 4, 15, 14, 30, 0, 2, 105, 0)),
            "updated_parsed": None,
            "published": None,
            "updated": None,
        }.get(k, d)
        result = _parse_feed_date(entry)
        assert isinstance(result, datetime)
        assert result.year == 2026
        assert result.tzinfo == timezone.utc
        assert result.hour == 14

    def test_parse_feed_date_parsed_field_is_utc_not_local_time(self, monkeypatch):
        import time

        original_tz = os.environ.get("TZ")
        monkeypatch.setenv("TZ", "America/Denver")
        time.tzset()
        try:
            entry = MagicMock()
            entry.get.side_effect = lambda k, d=None: {
                "published_parsed": time.struct_time(
                    (2026, 4, 15, 14, 30, 0, 2, 105, 0)
                ),
                "updated_parsed": None,
                "published": None,
                "updated": None,
            }.get(k, d)

            result = _parse_feed_date(entry)

            assert result == datetime(2026, 4, 15, 14, 30, tzinfo=timezone.utc)
        finally:
            if original_tz is None:
                monkeypatch.delenv("TZ", raising=False)
            else:
                monkeypatch.setenv("TZ", original_tz)
            time.tzset()

    def test_parse_feed_date_with_string_field(self):
        entry = MagicMock()
        entry.get.side_effect = lambda k, d=None: {
            "published_parsed": None,
            "updated_parsed": None,
            "published": "2026-04-15T14:30:00Z",
            "updated": None,
        }.get(k, d)
        result = _parse_feed_date(entry)
        assert isinstance(result, datetime)

    def test_parse_feed_date_returns_none_for_empty(self):
        entry = MagicMock()
        entry.get.return_value = None
        result = _parse_feed_date(entry)
        assert result is None

    @patch("sources.rss_feeds._fetch_direct")
    def test_fetch_rss_defaults_to_direct(self, mock_direct):
        mock_direct.return_value = []
        fetch_rss({"rss": {"provider": "direct", "feeds": []}})
        mock_direct.assert_called_once()

    @patch("sources.rss_feeds._fetch_from_freshrss")
    def test_fetch_rss_uses_freshrss_when_configured(self, mock_freshrss):
        mock_freshrss.return_value = []
        fetch_rss(
            {
                "rss": {
                    "provider": "freshrss",
                    "freshrss_url": "https://freshrss.example.com",
                    "freshrss_user": "user",
                    "freshrss_password": "pass",
                }
            }
        )
        mock_freshrss.assert_called_once()

    @patch("sources.rss_feeds._fetch_direct")
    @patch("sources.rss_feeds.requests.post")
    def test_freshrss_fallbacks_to_direct_on_error(self, mock_post, mock_direct):
        mock_post.side_effect = Exception("FreshRSS down")
        mock_direct.return_value = [{"source": "direct", "title": "test"}]
        result = fetch_rss(
            {
                "rss": {
                    "provider": "freshrss",
                    "freshrss_url": "https://freshrss.example.com",
                }
            }
        )
        mock_direct.assert_called_once()
        assert len(result) == 1

    @patch("sources.rss_feeds._fetch_feed_batch")
    def test_fetch_direct_preserves_ordered_circuit_breaker(self, mock_batch):
        feeds = [
            {"name": f"Feed {i}", "url": f"https://example.com/{i}", "category": "test"}
            for i in range(6)
        ]
        mock_batch.return_value = [
            {"content": None, "content_type": "", "status_code": 500, "error": "boom", "skipped": False},
            {"content": None, "content_type": "", "status_code": 500, "error": "boom", "skipped": False},
            {"content": None, "content_type": "", "status_code": 500, "error": "boom", "skipped": False},
            {"content": None, "content_type": "", "status_code": 500, "error": "boom", "skipped": False},
            {"content": None, "content_type": "", "status_code": 500, "error": "boom", "skipped": False},
            {"content": b"<rss />", "content_type": "application/rss+xml", "status_code": 200, "error": "", "skipped": False},
        ]

        result = _fetch_direct({"feeds": feeds})

        assert result == []
        mock_batch.assert_called_once()

    @patch("sources.rss_feeds._parse_feed_with_timeout")
    @patch("sources.rss_feeds._fetch_feed_batch")
    def test_fetch_direct_collects_items_after_parallel_fetch(self, mock_batch, mock_parse):
        feeds = [
            {"name": "Feed A", "url": "https://example.com/a", "category": "alpha"},
            {"name": "Feed B", "url": "https://example.com/b", "category": "beta"},
        ]
        mock_batch.return_value = [
            {"content": b"a", "content_type": "application/rss+xml", "status_code": 200, "error": "", "skipped": False},
            {"content": b"b", "content_type": "application/rss+xml", "status_code": 200, "error": "", "skipped": False},
        ]
        mock_parse.side_effect = [
            MagicMock(entries=[{"title": "A1", "link": "https://example.com/a1", "summary": "Alpha"}]),
            MagicMock(entries=[{"title": "B1", "link": "https://example.com/b1", "summary": "Beta"}]),
        ]

        result = _fetch_direct({"feeds": feeds})

        assert len(result) == 2
        assert {item["source"] for item in result} == {"Feed A", "Feed B"}

    @patch("sources.rss_feeds._fetch_feed_batch")
    def test_fetch_rss_with_diagnostics_reports_per_feed_status(self, mock_batch):
        feeds = [
            {"name": "Feed A", "url": "https://example.com/a", "category": "alpha"},
            {"name": "Feed B", "url": "https://example.com/b", "category": "beta"},
        ]
        mock_batch.return_value = [
            {
                "content": b"<rss />",
                "content_type": "application/rss+xml",
                "status_code": 200,
                "error": "",
                "skipped": False,
            },
            {
                "content": None,
                "content_type": "",
                "status_code": 401,
                "error": "blocked",
                "skipped": False,
            },
        ]

        items, diagnostics = fetch_rss_with_diagnostics({"rss": {"feeds": feeds}})

        assert items == []
        assert [entry["source"] for entry in diagnostics] == ["Feed A", "Feed B"]
        assert diagnostics[0]["status"] == "empty"
        assert diagnostics[1]["status"] == "http_error"
        assert diagnostics[1]["status_code"] == 401

    def test_items_from_html_index_extracts_article_links(self):
        html = b"""
        <html><body>
          <a href="/p/good-post">This is a plausible article title</a>
          <a href="/subscribe">Subscribe</a>
          <a href="https://example.com/p/second-post">Another valid article headline</a>
        </body></html>
        """
        feed = {
            "name": "HTML Feed",
            "url": "https://example.com/",
            "category": "test",
            "reliability": "primary-reporting",
            "analysis_mode": "headline_radar",
            "mode": "html_index",
            "cap": 5,
        }

        items = _items_from_html_index(feed, html)

        assert len(items) == 2
        assert items[0]["url"] == "https://example.com/p/good-post"
        assert items[1]["url"] == "https://example.com/p/second-post"
        assert items[0]["published"] == ""
        assert items[0]["freshness"] == "retrieved_at"
        assert items[0]["category"] == "test"
        assert items[0]["reliability"] == "primary-reporting"
        assert items[0]["analysis_mode"] == "headline_radar"
        assert datetime.fromisoformat(items[0]["fetched_at"]).tzinfo is not None

    def test_items_from_parsed_feed_caps_after_age_filtering(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=3)
        entries = [
            {
                "title": "Pinned old item",
                "link": "https://example.com/old",
                "summary": "Old",
                "published": old.isoformat(),
            },
            {
                "title": "Fresh one",
                "link": "https://example.com/1",
                "summary": "Fresh",
                "published": now.isoformat(),
            },
            {
                "title": "Fresh two",
                "link": "https://example.com/2",
                "summary": "Fresh",
                "published": now.isoformat(),
            },
        ]

        items = _items_from_parsed_feed(
            {
                "name": "Feed",
                "url": "https://example.com/feed",
                "cap": 2,
                "category": "science-biotech",
                "reliability": "primary-reporting",
                "analysis_mode": "headline_radar",
            },
            entries,
            now - timedelta(hours=36),
        )

        assert [item["title"] for item in items] == ["Fresh one", "Fresh two"]
        assert items[0]["category"] == "science-biotech"
        assert items[0]["reliability"] == "primary-reporting"
        assert items[0]["analysis_mode"] == "headline_radar"

    def test_skip_due_to_cooldown_returns_skip_result(self):
        feed = {"name": "Cool Feed", "url": "https://example.com/feed.xml"}
        state = {
            _state_key(feed): {
                "cooldown_until": datetime.now(timezone.utc).timestamp() + 300,
                "last_status": 429,
                "last_error": "too many requests",
            }
        }

        result = _skip_due_to_cooldown(feed, state)

        assert result is not None
        assert result["skipped"] is True
        assert result["status_code"] == 429

    def test_skip_due_to_cooldown_reads_legacy_name_key(self):
        feed = {"name": "Cool Feed", "url": "https://example.com/feed.xml"}
        state = {
            "Cool Feed": {
                "cooldown_until": datetime.now(timezone.utc).timestamp() + 300,
                "last_status": 429,
                "last_error": "too many requests",
            }
        }

        result = _skip_due_to_cooldown(feed, state)

        assert result is not None
        assert result["skipped"] is True
