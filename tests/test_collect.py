"""Tests for stages/collect.py — source orchestration."""

import sys
import os
import threading
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.collect import run


class TestCollectRun:
    def _make_config(self):
        return {
            "digest": {
                "markets": {"enabled": True},
                "spiritual": {"enabled": True},
            },
            "llm": {"provider": "fireworks"},
            "local_news": {"sources": []},
            "rss": {"feeds": []},
            "youtube": {"analysis_channels": []},
        }

    @patch("stages.collect.fetch_weather")
    @patch("stages.collect.fetch_markets")
    @patch("stages.collect.fetch_upcoming_launches")
    @patch("stages.collect.fetch_hackernews")
    @patch("stages.collect.fetch_github_trending")
    @patch("stages.collect.fetch_astronomy")
    @patch("stages.collect.fetch_on_this_day")
    @patch("stages.collect.get_upcoming_church_events")
    @patch("stages.collect.get_upcoming_holidays")
    @patch("stages.collect.fetch_economic_calendar")
    @patch("stages.collect.get_current_lesson")
    @patch("stages.collect.fetch_analysis_transcripts")
    @patch("stages.collect.fetch_rss_with_diagnostics")
    @patch("stages.collect.sanitize_all_sources")
    def test_calls_all_sources(
        self,
        mock_sanitize,
        mock_rss,
        mock_yt,
        mock_lesson,
        mock_econ_cal,
        mock_holidays,
        mock_church,
        mock_history,
        mock_astronomy,
        mock_github,
        mock_hn,
        mock_launches,
        mock_markets,
        mock_weather,
    ):
        mock_weather.return_value = {"temp": 72}
        mock_markets.return_value = []
        mock_launches.return_value = []
        mock_hn.return_value = []
        mock_github.return_value = []
        mock_astronomy.return_value = {}
        mock_history.return_value = {}
        mock_church.return_value = []
        mock_holidays.return_value = []
        mock_econ_cal.return_value = []
        mock_lesson.return_value = {}
        mock_yt.return_value = []
        mock_rss.return_value = ([], [])
        mock_sanitize.return_value = {
            "rss": [],
            "local_news": [],
            "analysis_transcripts": [],
        }

        config = self._make_config()
        run({}, config)

        mock_weather.assert_called_once_with(config)
        mock_markets.assert_called_once_with(config)
        mock_launches.assert_called_once()
        mock_hn.assert_called_once_with(config)
        mock_github.assert_called_once_with(config)
        mock_astronomy.assert_called_once_with(config)
        mock_history.assert_called_once_with(config)
        mock_church.assert_called_once()
        mock_holidays.assert_called_once_with(days=10)
        mock_econ_cal.assert_called_once_with(config)
        mock_lesson.assert_called_once_with(config)
        mock_yt.assert_called_once_with(config)
        mock_rss.assert_called_once_with(config)
        mock_sanitize.assert_called_once()

    @patch("stages.collect.fetch_weather")
    @patch("stages.collect.fetch_markets")
    @patch("stages.collect.fetch_upcoming_launches")
    @patch("stages.collect.fetch_hackernews")
    @patch("stages.collect.fetch_github_trending")
    @patch("stages.collect.fetch_astronomy")
    @patch("stages.collect.fetch_on_this_day")
    @patch("stages.collect.get_upcoming_church_events")
    @patch("stages.collect.get_upcoming_holidays")
    @patch("stages.collect.fetch_economic_calendar")
    @patch("stages.collect.get_current_lesson")
    @patch("stages.collect.fetch_analysis_transcripts")
    @patch("stages.collect.fetch_rss_with_diagnostics")
    @patch("stages.collect.sanitize_all_sources")
    def test_markets_disabled_when_config_says_so(
        self,
        mock_sanitize,
        mock_rss,
        mock_yt,
        mock_lesson,
        mock_econ_cal,
        mock_holidays,
        mock_church,
        mock_history,
        mock_astronomy,
        mock_github,
        mock_hn,
        mock_launches,
        mock_markets,
        mock_weather,
    ):
        mock_weather.return_value = {"temp": 72}
        mock_launches.return_value = []
        mock_hn.return_value = []
        mock_github.return_value = []
        mock_astronomy.return_value = {}
        mock_history.return_value = {}
        mock_church.return_value = []
        mock_holidays.return_value = []
        mock_econ_cal.return_value = []
        mock_lesson.return_value = {}
        mock_yt.return_value = []
        mock_rss.return_value = ([], [])
        mock_sanitize.return_value = {
            "rss": [],
            "local_news": [],
            "analysis_transcripts": [],
        }

        config = self._make_config()
        config["digest"]["markets"]["enabled"] = False
        run({}, config)

        mock_markets.assert_not_called()

    @patch("stages.collect.fetch_weather")
    @patch("stages.collect.fetch_markets")
    @patch("stages.collect.fetch_upcoming_launches")
    @patch("stages.collect.fetch_hackernews")
    @patch("stages.collect.fetch_github_trending")
    @patch("stages.collect.fetch_astronomy")
    @patch("stages.collect.fetch_on_this_day")
    @patch("stages.collect.get_upcoming_church_events")
    @patch("stages.collect.get_upcoming_holidays")
    @patch("stages.collect.fetch_economic_calendar")
    @patch("stages.collect.get_current_lesson")
    @patch("stages.collect.fetch_analysis_transcripts")
    @patch("stages.collect.fetch_rss_with_diagnostics")
    @patch("stages.collect.sanitize_all_sources")
    def test_spiritual_disabled_when_config_says_so(
        self,
        mock_sanitize,
        mock_rss,
        mock_yt,
        mock_lesson,
        mock_econ_cal,
        mock_holidays,
        mock_church,
        mock_history,
        mock_astronomy,
        mock_github,
        mock_hn,
        mock_launches,
        mock_markets,
        mock_weather,
    ):
        mock_weather.return_value = {"temp": 72}
        mock_markets.return_value = []
        mock_launches.return_value = []
        mock_hn.return_value = []
        mock_github.return_value = []
        mock_astronomy.return_value = {}
        mock_history.return_value = {}
        mock_church.return_value = []
        mock_holidays.return_value = []
        mock_econ_cal.return_value = []
        mock_lesson.return_value = {}  # Consistent with other tests
        mock_yt.return_value = []
        mock_rss.return_value = ([], [])
        mock_sanitize.return_value = {
            "rss": [],
            "local_news": [],
            "analysis_transcripts": [],
        }

        config = self._make_config()
        config["digest"]["spiritual"]["enabled"] = False
        run({}, config)

        mock_lesson.assert_not_called()

    @patch("stages.collect.fetch_weather")
    @patch("stages.collect.fetch_markets")
    @patch("stages.collect.fetch_upcoming_launches")
    @patch("stages.collect.fetch_hackernews")
    @patch("stages.collect.fetch_github_trending")
    @patch("stages.collect.fetch_astronomy")
    @patch("stages.collect.fetch_on_this_day")
    @patch("stages.collect.get_upcoming_church_events")
    @patch("stages.collect.get_upcoming_holidays")
    @patch("stages.collect.fetch_economic_calendar")
    @patch("stages.collect.get_current_lesson")
    @patch("stages.collect.fetch_analysis_transcripts")
    @patch("stages.collect.fetch_rss_with_diagnostics")
    @patch("stages.collect.sanitize_all_sources")
    def test_youtube_failure_doesnt_crash_pipeline(
        self,
        mock_sanitize,
        mock_rss,
        mock_yt,
        mock_lesson,
        mock_econ_cal,
        mock_holidays,
        mock_church,
        mock_history,
        mock_astronomy,
        mock_github,
        mock_hn,
        mock_launches,
        mock_markets,
        mock_weather,
    ):
        mock_weather.return_value = {"temp": 72}
        mock_markets.return_value = []
        mock_launches.return_value = []
        mock_hn.return_value = []
        mock_github.return_value = []
        mock_astronomy.return_value = {}
        mock_history.return_value = {}
        mock_church.return_value = []
        mock_holidays.return_value = []
        mock_econ_cal.return_value = []
        mock_lesson.return_value = {}
        mock_yt.side_effect = Exception("YouTube API down")
        mock_rss.return_value = ([], [])
        mock_sanitize.return_value = {
            "rss": [],
            "local_news": [],
            "analysis_transcripts": [],
        }

        result = run({}, self._make_config())

        assert result["raw_sources"]["analysis_transcripts"] == []

    @patch("stages.collect.fetch_weather")
    @patch("stages.collect.fetch_markets")
    @patch("stages.collect.fetch_upcoming_launches")
    @patch("stages.collect.fetch_hackernews")
    @patch("stages.collect.fetch_github_trending")
    @patch("stages.collect.fetch_astronomy")
    @patch("stages.collect.fetch_on_this_day")
    @patch("stages.collect.get_upcoming_church_events")
    @patch("stages.collect.get_upcoming_holidays")
    @patch("stages.collect.fetch_economic_calendar")
    @patch("stages.collect.get_current_lesson")
    @patch("stages.collect.fetch_analysis_transcripts")
    @patch("stages.collect.fetch_rss_with_diagnostics")
    @patch("stages.collect.sanitize_all_sources")
    def test_local_news_fetched_when_configured(
        self,
        mock_sanitize,
        mock_rss,
        mock_yt,
        mock_lesson,
        mock_econ_cal,
        mock_holidays,
        mock_church,
        mock_history,
        mock_astronomy,
        mock_github,
        mock_hn,
        mock_launches,
        mock_markets,
        mock_weather,
    ):
        mock_weather.return_value = {"temp": 72}
        mock_markets.return_value = []
        mock_launches.return_value = []
        mock_hn.return_value = []
        mock_github.return_value = []
        mock_astronomy.return_value = {}
        mock_history.return_value = {}
        mock_church.return_value = []
        mock_holidays.return_value = []
        mock_econ_cal.return_value = []
        mock_lesson.return_value = {}
        mock_yt.return_value = []
        mock_rss.return_value = ([], [])
        mock_sanitize.return_value = {
            "rss": [],
            "local_news": [],
            "analysis_transcripts": [],
        }

        config = self._make_config()
        config["local_news"] = {
            "sources": [{"name": "Local", "url": "https://local.com/feed"}]
        }
        run({}, config)

        assert mock_rss.call_count == 2

    @patch("stages.collect.fetch_weather")
    @patch("stages.collect.fetch_markets")
    @patch("stages.collect.fetch_upcoming_launches")
    @patch("stages.collect.fetch_hackernews")
    @patch("stages.collect.fetch_github_trending")
    @patch("stages.collect.fetch_astronomy")
    @patch("stages.collect.fetch_on_this_day")
    @patch("stages.collect.get_upcoming_church_events")
    @patch("stages.collect.get_upcoming_holidays")
    @patch("stages.collect.fetch_economic_calendar")
    @patch("stages.collect.get_current_lesson")
    @patch("stages.collect.fetch_analysis_transcripts")
    @patch("stages.collect.fetch_rss_with_diagnostics")
    @patch("stages.collect.sanitize_all_sources")
    def test_local_news_empty_when_no_sources(
        self,
        mock_sanitize,
        mock_rss,
        mock_yt,
        mock_lesson,
        mock_econ_cal,
        mock_holidays,
        mock_church,
        mock_history,
        mock_astronomy,
        mock_github,
        mock_hn,
        mock_launches,
        mock_markets,
        mock_weather,
    ):
        mock_weather.return_value = {"temp": 72}
        mock_markets.return_value = []
        mock_launches.return_value = []
        mock_hn.return_value = []
        mock_github.return_value = []
        mock_astronomy.return_value = {}
        mock_history.return_value = {}
        mock_church.return_value = []
        mock_holidays.return_value = []
        mock_econ_cal.return_value = []
        mock_lesson.return_value = {}
        mock_yt.return_value = []
        mock_rss.return_value = ([], [])
        mock_sanitize.return_value = {
            "rss": [],
            "local_news": [],
            "analysis_transcripts": [],
        }

        config = self._make_config()
        config["local_news"] = {"sources": []}
        result = run({}, config)

        assert result["raw_sources"]["local_news"] == []
        assert mock_rss.call_count == 1

    @patch("stages.collect.fetch_weather")
    @patch("stages.collect.fetch_markets")
    @patch("stages.collect.fetch_upcoming_launches")
    @patch("stages.collect.fetch_hackernews")
    @patch("stages.collect.fetch_github_trending")
    @patch("stages.collect.fetch_astronomy")
    @patch("stages.collect.fetch_on_this_day")
    @patch("stages.collect.get_upcoming_church_events")
    @patch("stages.collect.get_upcoming_holidays")
    @patch("stages.collect.fetch_economic_calendar")
    @patch("stages.collect.get_current_lesson")
    @patch("stages.collect.fetch_analysis_transcripts")
    @patch("stages.collect.fetch_rss_with_diagnostics")
    @patch("stages.collect.sanitize_all_sources")
    def test_rss_fetch_runs_on_main_thread(
        self,
        mock_sanitize,
        mock_rss,
        mock_yt,
        mock_lesson,
        mock_econ_cal,
        mock_holidays,
        mock_church,
        mock_history,
        mock_astronomy,
        mock_github,
        mock_hn,
        mock_launches,
        mock_markets,
        mock_weather,
    ):
        mock_weather.return_value = {"temp": 72}
        mock_markets.return_value = []
        mock_launches.return_value = []
        mock_hn.return_value = []
        mock_github.return_value = []
        mock_astronomy.return_value = {}
        mock_history.return_value = {}
        mock_church.return_value = []
        mock_holidays.return_value = []
        mock_econ_cal.return_value = []
        mock_lesson.return_value = {}
        mock_yt.return_value = []
        mock_sanitize.return_value = {
            "rss": [],
            "local_news": [],
            "analysis_transcripts": [],
        }

        def _fetch_rss_on_main_thread(_config):
            assert threading.current_thread() is threading.main_thread()
            return [], []

        mock_rss.side_effect = _fetch_rss_on_main_thread

        run({}, self._make_config())

        mock_rss.assert_called_once()

    @patch("stages.collect.fetch_weather")
    @patch("stages.collect.fetch_markets")
    @patch("stages.collect.fetch_upcoming_launches")
    @patch("stages.collect.fetch_hackernews")
    @patch("stages.collect.fetch_github_trending")
    @patch("stages.collect.fetch_astronomy")
    @patch("stages.collect.fetch_on_this_day")
    @patch("stages.collect.get_upcoming_church_events")
    @patch("stages.collect.get_upcoming_holidays")
    @patch("stages.collect.fetch_economic_calendar")
    @patch("stages.collect.get_current_lesson")
    @patch("stages.collect.fetch_analysis_transcripts")
    @patch("stages.collect.fetch_rss_with_diagnostics")
    @patch("stages.collect.sanitize_all_sources")
    def test_youtube_fetch_runs_on_main_thread(
        self,
        mock_sanitize,
        mock_rss,
        mock_yt,
        mock_lesson,
        mock_econ_cal,
        mock_holidays,
        mock_church,
        mock_history,
        mock_astronomy,
        mock_github,
        mock_hn,
        mock_launches,
        mock_markets,
        mock_weather,
    ):
        mock_weather.return_value = {"temp": 72}
        mock_markets.return_value = []
        mock_launches.return_value = []
        mock_hn.return_value = []
        mock_github.return_value = []
        mock_astronomy.return_value = {}
        mock_history.return_value = {}
        mock_church.return_value = []
        mock_holidays.return_value = []
        mock_econ_cal.return_value = []
        mock_lesson.return_value = {}
        mock_rss.return_value = ([], [])
        mock_sanitize.return_value = {
            "rss": [],
            "local_news": [],
            "analysis_transcripts": [],
        }

        def _fetch_youtube_on_main_thread(_config):
            assert threading.current_thread() is threading.main_thread()
            return []

        mock_yt.side_effect = _fetch_youtube_on_main_thread

        run({}, self._make_config())

        mock_yt.assert_called_once()

    @patch("stages.collect.fetch_weather")
    @patch("stages.collect.fetch_markets")
    @patch("stages.collect.fetch_upcoming_launches")
    @patch("stages.collect.get_upcoming_church_events")
    @patch("stages.collect.get_upcoming_holidays")
    @patch("stages.collect.fetch_economic_calendar")
    @patch("stages.collect.get_current_lesson")
    @patch("stages.collect.fetch_analysis_transcripts")
    @patch("stages.collect.fetch_rss_with_diagnostics")
    @patch("stages.collect.sanitize_all_sources")
    def test_source_counts_included(
        self,
        mock_sanitize,
        mock_rss,
        mock_yt,
        mock_lesson,
        mock_econ_cal,
        mock_holidays,
        mock_church,
        mock_launches,
        mock_markets,
        mock_weather,
    ):
        mock_weather.return_value = {"temp": 72}
        mock_markets.return_value = []
        mock_launches.return_value = []
        mock_church.return_value = []
        mock_holidays.return_value = []
        mock_econ_cal.return_value = []
        mock_lesson.return_value = {}
        mock_yt.return_value = [{"title": "v1"}]
        mock_rss.return_value = ([{"title": "a1"}, {"title": "a2"}], [])
        mock_sanitize.return_value = {
            "rss": [{"title": "a1"}, {"title": "a2"}],
            "local_news": [],
            "analysis_transcripts": [{"title": "v1"}],
            "source_counts": {
                "analysis_transcripts": 1,
                "rss_items": 2,
                "local_news_items": 0,
                "hackernews_items": 0,
                "github_trending_items": 0,
                "astronomy_events": 0,
                "history_items": 0,
            },
        }

        result = run({}, self._make_config())

        assert result["raw_sources"]["source_counts"]["analysis_transcripts"] == 1
        assert result["raw_sources"]["source_counts"]["rss_items"] == 2
        assert result["raw_sources"]["source_counts"]["local_news_items"] == 0
        assert result["raw_sources"]["source_counts"]["hackernews_items"] == 0

    @patch("stages.collect.fetch_weather")
    @patch("stages.collect.fetch_markets")
    @patch("stages.collect.fetch_upcoming_launches")
    @patch("stages.collect.fetch_hackernews")
    @patch("stages.collect.fetch_github_trending")
    @patch("stages.collect.fetch_astronomy")
    @patch("stages.collect.fetch_on_this_day")
    @patch("stages.collect.get_upcoming_church_events")
    @patch("stages.collect.get_upcoming_holidays")
    @patch("stages.collect.fetch_economic_calendar")
    @patch("stages.collect.get_current_lesson")
    @patch("stages.collect.fetch_analysis_transcripts")
    @patch("stages.collect.fetch_rss_with_diagnostics")
    @patch("stages.collect.sanitize_all_sources")
    def test_returns_raw_sources_key(
        self,
        mock_sanitize,
        mock_rss,
        mock_yt,
        mock_lesson,
        mock_econ_cal,
        mock_holidays,
        mock_church,
        mock_history,
        mock_astronomy,
        mock_github,
        mock_hn,
        mock_launches,
        mock_markets,
        mock_weather,
    ):
        mock_weather.return_value = {"temp": 72}
        mock_markets.return_value = []
        mock_launches.return_value = []
        mock_hn.return_value = []
        mock_github.return_value = []
        mock_astronomy.return_value = {}
        mock_history.return_value = {}
        mock_church.return_value = []
        mock_holidays.return_value = []
        mock_econ_cal.return_value = []
        mock_lesson.return_value = {}
        mock_yt.return_value = []
        mock_rss.return_value = ([], [])
        mock_sanitize.return_value = {
            "rss": [],
            "local_news": [],
            "analysis_transcripts": [],
        }

        result = run({}, self._make_config())

        assert "raw_sources" in result
        assert isinstance(result["raw_sources"], dict)
        assert "collect_diagnostics" in result
        assert "sources" in result["collect_diagnostics"]

    @patch("stages.collect.fetch_weather")
    @patch("stages.collect.fetch_markets")
    @patch("stages.collect.fetch_upcoming_launches")
    @patch("stages.collect.fetch_hackernews")
    @patch("stages.collect.fetch_github_trending")
    @patch("stages.collect.fetch_astronomy")
    @patch("stages.collect.fetch_on_this_day")
    @patch("stages.collect.get_upcoming_church_events")
    @patch("stages.collect.get_upcoming_holidays")
    @patch("stages.collect.fetch_economic_calendar")
    @patch("stages.collect.get_current_lesson")
    @patch("stages.collect.fetch_analysis_transcripts")
    @patch("stages.collect.fetch_rss_with_diagnostics")
    @patch("stages.collect.sanitize_all_sources")
    def test_collect_diagnostics_propagate_source_status(
        self,
        mock_sanitize,
        mock_rss,
        mock_yt,
        mock_lesson,
        mock_econ_cal,
        mock_holidays,
        mock_church,
        mock_history,
        mock_astronomy,
        mock_github,
        mock_hn,
        mock_launches,
        mock_markets,
        mock_weather,
    ):
        """Verify ok_empty / degraded / failed statuses from source modules surface in diagnostics."""
        mock_weather.return_value = {"temp": 72}
        mock_markets.return_value = []
        mock_launches.return_value = []
        mock_hn.return_value = []
        mock_github.return_value = []
        mock_astronomy.return_value = {
            "iss_passes": [],
            "moon_phase": "Full Moon",
            "_diagnostic": {"status": "degraded", "error": "No N2YO key"},
        }
        mock_history.return_value = {
            "selected": [],
            "events": [],
            "month": 4,
            "day": 29,
            "_diagnostic": {"status": "failed", "error": "API down"},
        }
        mock_church.return_value = [
            {"_diagnostic": {"status": "ok_empty", "error": "No conference dates"}}
        ]
        mock_holidays.return_value = [
            {"_diagnostic": {"status": "ok_empty", "error": "No holidays"}}
        ]
        mock_econ_cal.return_value = []
        mock_lesson.return_value = {}
        mock_yt.return_value = []
        mock_rss.return_value = ([], [])
        mock_sanitize.return_value = {
            "rss": [],
            "local_news": [],
            "analysis_transcripts": [],
        }

        result = run({}, self._make_config())

        sources = result["collect_diagnostics"]["sources"]
        by_name = {d["source"]: d for d in sources}
        assert by_name["astronomy"]["status"] == "degraded"
        assert "No N2YO key" in by_name["astronomy"]["error"]
        assert by_name["on_this_day"]["status"] == "failed"
        assert "API down" in by_name["on_this_day"]["error"]
        # calendar aggregates church_events + holidays + economic_calendar;
        # the diagnostic is propagated from the first nested _diagnostic found
        assert by_name["calendar"]["status"] == "ok_empty"


