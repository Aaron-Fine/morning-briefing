"""Tests for scripts/source_health.py."""

import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.source_health import compute_source_health, _load_feed_healths


class TestLoadFeedHealths:
    def test_returns_health_from_config(self):
        config = {
            "rss": {
                "feeds": [
                    {"name": "A", "health": "low_frequency"},
                    {"name": "B"},
                    {"name": "C", "health": "broken"},
                ]
            }
        }
        result = _load_feed_healths(config)
        assert result == {"A": "low_frequency", "B": "active", "C": "broken"}


class TestComputeSourceHealth:
    def test_computes_health_for_empty_artifacts(self):
        config = {
            "rss": {
                "feeds": [
                    {"name": "Test Feed", "health": "active"},
                ]
            }
        }
        report = compute_source_health(config, artifacts_root=Path("/nonexistent"))
        assert report["schema_version"] == 1
        assert len(report["feeds"]) == 1
        feed = report["feeds"][0]
        assert feed["name"] == "Test Feed"
        assert feed["health"] == "active"
        assert feed["computed_health"] == "degraded"
        assert "Zero items" in feed["observations"][0]

    def test_respects_existing_low_frequency(self):
        config = {
            "rss": {
                "feeds": [
                    {"name": "Rare Feed", "health": "low_frequency"},
                ]
            }
        }
        report = compute_source_health(config, artifacts_root=Path("/nonexistent"))
        feed = report["feeds"][0]
        assert feed["computed_health"] == "low_frequency"

    def test_overrides_active_when_short_text(self):
        config = {
            "rss": {
                "feeds": [
                    {"name": "Short Feed", "health": "active"},
                ]
            }
        }
        # Mock artifacts with short summaries
        artifact = MagicMock()
        artifact.__enter__ = MagicMock(return_value={
            "date": "2026-04-29",
            "rss_items": [
                {"source": "Short Feed", "summary": "hi"},
            ],
            "enrich_records": [],
        })
        artifact.__exit__ = MagicMock(return_value=False)

        with patch("scripts.source_health.load_artifacts") as mock_load:
            mock_load.return_value = [{
                "date": "2026-04-29",
                "rss_items": [
                    {"source": "Short Feed", "summary": "hi"},
                ],
                "enrich_records": [],
            }]
            report = compute_source_health(config, window_days=1)
            feed = report["feeds"][0]
            assert feed["computed_health"] == "enrichment_required"
            obs_text = " ".join(feed["observations"])
            assert "Short RSS bodies" in obs_text
