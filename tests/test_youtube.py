"""Tests for sources/youtube.py — helper functions only (no network calls)."""

import sys
import os
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sources.youtube import _parse_date


class TestParseDate:
    def test_valid_date(self):
        result = _parse_date("20260410")
        assert result == datetime(2026, 4, 10, tzinfo=timezone.utc)

    def test_valid_date_different_month(self):
        result = _parse_date("20260101")
        assert result == datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_empty_string_returns_none(self):
        assert _parse_date("") is None

    def test_none_returns_none(self):
        assert _parse_date(None) is None

    def test_wrong_length_returns_none(self):
        assert _parse_date("2026041") is None
        assert _parse_date("202604101") is None

    def test_invalid_date_returns_none(self):
        assert _parse_date("not-a-date") is None
        assert _parse_date("20261301") is None  # invalid month
        assert _parse_date("20260432") is None  # invalid day


class TestFetchAnalysisTranscripts:
    @patch("sources.youtube.yt_dlp.YoutubeDL")
    @patch("sources.youtube.YouTubeTranscriptApi")
    @patch("sources.youtube.datetime")
    def test_empty_channels_returns_empty(self, mock_dt, mock_api, mock_ydl):
        from sources.youtube import fetch_analysis_transcripts

        mock_dt.now.return_value = datetime(2026, 4, 10, tzinfo=timezone.utc)
        config = {"youtube": {"analysis_channels": [], "lookback_hours": 48}}
        result = fetch_analysis_transcripts(config)
        assert result == []

    @patch("sources.youtube.yt_dlp.YoutubeDL")
    @patch("sources.youtube.datetime")
    def test_missing_handle_skips_channel(self, mock_dt, mock_ydl):
        from sources.youtube import fetch_analysis_transcripts

        mock_dt.now.return_value = datetime(2026, 4, 10, tzinfo=timezone.utc)
        config = {
            "youtube": {
                "analysis_channels": [{"name": "Test Channel"}],
                "lookback_hours": 48,
            }
        }
        result = fetch_analysis_transcripts(config)
        assert result == []

    @patch("sources.youtube.yt_dlp.YoutubeDL")
    @patch("sources.youtube.datetime")
    def test_ydl_exception_returns_empty(self, mock_dt, mock_ydl):
        from sources.youtube import fetch_analysis_transcripts

        mock_dt.now.return_value = datetime(2026, 4, 10, tzinfo=timezone.utc)
        mock_ydl.side_effect = Exception("Network error")
        config = {
            "youtube": {
                "analysis_channels": [{"name": "Test", "handle": "testchannel"}],
                "lookback_hours": 48,
            }
        }
        result = fetch_analysis_transcripts(config)
        assert result == []

    @patch("sources.youtube.yt_dlp.YoutubeDL")
    @patch("sources.youtube.YouTubeTranscriptApi")
    @patch("sources.youtube.datetime")
    def test_filters_old_videos(self, mock_dt, mock_api, mock_ydl):
        from sources.youtube import fetch_analysis_transcripts

        now = datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        # Create a mock info dict with one recent and one old video
        mock_ydl_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_ydl_instance
        mock_ydl_instance.extract_info.return_value = {
            "entries": [
                {
                    "id": "video1",
                    "title": "Recent Video",
                    "upload_date": "20260410",
                },
                {
                    "id": "video2",
                    "title": "Old Video",
                    "upload_date": "20260101",
                },
            ]
        }

        mock_api.return_value.fetch.return_value = MagicMock(
            snippets=[MagicMock(text="Test transcript")]
        )

        config = {
            "youtube": {
                "analysis_channels": [{"name": "Test", "handle": "testchannel"}],
                "lookback_hours": 48,
            }
        }
        result = fetch_analysis_transcripts(config)
        assert len(result) == 1
        assert result[0]["title"] == "Recent Video"

    @patch("sources.youtube.yt_dlp.YoutubeDL")
    @patch("sources.youtube.YouTubeTranscriptApi")
    @patch("sources.youtube.datetime")
    def test_skips_videos_without_transcript(self, mock_dt, mock_api, mock_ydl):
        from sources.youtube import fetch_analysis_transcripts

        now = datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        mock_ydl_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_ydl_instance
        mock_ydl_instance.extract_info.return_value = {
            "entries": [
                {
                    "id": "video1",
                    "title": "No Transcript Video",
                    "upload_date": "20260410",
                }
            ]
        }

        mock_api.return_value.fetch.side_effect = Exception("No transcript available")

        config = {
            "youtube": {
                "analysis_channels": [{"name": "Test", "handle": "testchannel"}],
                "lookback_hours": 48,
            }
        }
        result = fetch_analysis_transcripts(config)
        assert result == []
