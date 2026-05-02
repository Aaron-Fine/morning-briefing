"""Tests for validate_new_feeds.py --new-only and rule checks."""

import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.validate_new_feeds import (
    _validate_new_feed_rules,
    _find_new_feeds,
)


class TestValidateNewFeedRules:
    def test_valid_feed_passes(self):
        desk_cats = {"maritime", "ai-tech"}
        feed = {
            "url": "https://example.com/feed",
            "category": "maritime",
            "health": "active",
        }
        assert _validate_new_feed_rules(feed, desk_cats) == []

    def test_missing_category_fails(self):
        desk_cats = {"maritime"}
        feed = {"url": "https://example.com/feed", "health": "active"}
        errors = _validate_new_feed_rules(feed, desk_cats)
        assert any("missing category" in e for e in errors)

    def test_unrouted_category_fails(self):
        desk_cats = {"maritime"}
        feed = {"url": "https://example.com/feed", "category": "unknown", "health": "active"}
        errors = _validate_new_feed_rules(feed, desk_cats)
        assert any("not routed" in e for e in errors)

    def test_missing_health_fails(self):
        desk_cats = {"maritime"}
        feed = {"url": "https://example.com/feed", "category": "maritime"}
        errors = _validate_new_feed_rules(feed, desk_cats)
        assert any("missing health" in e for e in errors)

    def test_invalid_health_fails(self):
        desk_cats = {"maritime"}
        feed = {"url": "https://example.com/feed", "category": "maritime", "health": "bad"}
        errors = _validate_new_feed_rules(feed, desk_cats)
        assert any("invalid health" in e for e in errors)

    def test_low_frequency_health_accepted(self):
        desk_cats = {"maritime"}
        feed = {"url": "https://example.com/feed", "category": "maritime", "health": "low_frequency"}
        assert _validate_new_feed_rules(feed, desk_cats) == []

    def test_active_feed_requires_recent_item(self):
        desk_cats = {"maritime"}
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        feed = {"url": "https://example.com/feed", "category": "maritime", "health": "active"}
        result = {"status": "OK", "latest": old_date}
        errors = _validate_new_feed_rules(feed, desk_cats, result)
        assert any("last 7 days" in e for e in errors)

    def test_low_frequency_feed_is_exempt_from_recent_item_rule(self):
        desk_cats = {"maritime"}
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        feed = {
            "url": "https://example.com/feed",
            "category": "maritime",
            "health": "low_frequency",
        }
        result = {"status": "OK", "latest": old_date}
        assert _validate_new_feed_rules(feed, desk_cats, result) == []


class TestFindNewFeeds:
    def test_returns_only_new_urls(self):
        current = [
            {"url": "https://old.com/feed", "name": "Old"},
            {"url": "https://new.com/feed", "name": "New"},
        ]
        previous = [
            {"url": "https://old.com/feed", "name": "Old"},
        ]
        with patch("scripts.validate_new_feeds._load_configured_feeds", return_value=current), \
             patch("scripts.validate_new_feeds._previous_commit_feeds", return_value=previous):
            result = _find_new_feeds()
            assert len(result) == 1
            assert result[0]["url"] == "https://new.com/feed"

    def test_empty_previous_returns_all(self):
        current = [
            {"url": "https://a.com/feed", "name": "A"},
        ]
        with patch("scripts.validate_new_feeds._load_configured_feeds", return_value=current), \
             patch("scripts.validate_new_feeds._previous_commit_feeds", return_value=[]):
            result = _find_new_feeds()
            assert len(result) == 1

    def test_no_new_feeds_returns_empty(self):
        current = [
            {"url": "https://a.com/feed", "name": "A"},
        ]
        with patch("scripts.validate_new_feeds._load_configured_feeds", return_value=current), \
             patch("scripts.validate_new_feeds._previous_commit_feeds", return_value=current):
            result = _find_new_feeds()
            assert result == []

    def test_missing_git_metadata_returns_empty(self):
        current = [
            {"url": "https://a.com/feed", "name": "A"},
        ]
        with patch("scripts.validate_new_feeds._load_configured_feeds", return_value=current), \
             patch("scripts.validate_new_feeds._previous_commit_feeds", return_value=None):
            result = _find_new_feeds()
            assert result == []
