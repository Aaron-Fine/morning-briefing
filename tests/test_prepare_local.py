"""Tests for stages/prepare_local.py — press release filtering."""

import sys
import os

# Add project root to path so we can import stages/ modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.prepare_local import _is_local_news, run


class TestIsLocalNews:
    """Tests for the _is_local_news filter function."""

    def test_genuine_local_item_passes(self):
        item = {
            "url": "https://www.cachevalleydaily.com/news/city-council-meeting",
            "title": "City Council Votes on Zoning",
            "summary": "The Cache Valley city council voted 5-2 to rezone...",
        }
        assert _is_local_news(item) is True

    def test_press_release_url_path_blocked(self):
        item = {
            "url": "https://www.hjnews.com/press_releases/company-announces-merger",
            "title": "Company Announces Merger",
            "summary": "A local company announced a merger today.",
        }
        assert _is_local_news(item) is False

    def test_prnewswire_in_summary_blocked(self):
        item = {
            "url": "https://www.hjnews.com/news/some-article",
            "title": "Product Launch",
            "summary": "PRNewswire — Acme Corp launched a new widget today.",
        }
        assert _is_local_news(item) is False

    def test_business_wire_in_summary_blocked(self):
        item = {
            "url": "https://www.hjnews.com/news/some-article",
            "title": "Earnings Report",
            "summary": "Business Wire — Acme Corp reported Q3 earnings.",
        }
        assert _is_local_news(item) is False

    def test_globenewswire_in_summary_blocked(self):
        item = {
            "url": "https://www.hjnews.com/news/some-article",
            "title": "Partnership Announcement",
            "summary": "GlobeNewswire — Two companies partnered today.",
        }
        assert _is_local_news(item) is False

    def test_pr_newswire_spaced_in_summary_blocked(self):
        item = {
            "url": "https://www.hjnews.com/news/some-article",
            "title": "Press Release",
            "summary": "PR Newswire — An announcement was made.",
        }
        assert _is_local_news(item) is False

    def test_empty_url_and_summary_passes(self):
        """Edge case: missing fields should not crash and should pass through."""
        item = {"url": "", "summary": ""}
        assert _is_local_news(item) is True

    def test_missing_url_and_summary_keys_passes(self):
        """Edge case: missing keys should not crash."""
        item = {}
        assert _is_local_news(item) is True

    def test_none_url_and_summary_passes(self):
        """Edge case: None values should not crash."""
        item = {"url": None, "summary": None}
        assert _is_local_news(item) is True


def test_run_demotes_empty_summary_items():
    items = [
        {"title": "Livestream", "summary": "", "url": "https://local/1"},
        {
            "title": "Council",
            "summary": "A detailed local summary with enough context to be useful.",
            "url": "https://local/2",
        },
    ]
    result = run(
        {"raw_sources": {"local_news": items}},
        {"digest": {"local": {"max_items": 1}}},
    )
    assert result["local_items"][0]["title"] == "Council"
