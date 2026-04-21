"""Tests for article enrichment cache."""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sources.article_cache import ArticleCache


def test_cache_put_then_get(tmp_path):
    cache = ArticleCache(tmp_path)
    cache.put("https://x/", "ok", 200, "Summary", 1200, "fetched_html", "Src", "")
    entry = cache.get("https://x/")
    assert entry is not None
    assert entry.canonical_summary == "Summary"
    assert entry.source_text_origin == "fetched_html"
    assert entry.summary_length == len("Summary")


def test_cache_ok_entry_expires_after_ttl(tmp_path):
    cache = ArticleCache(tmp_path, ttl_days=30)
    cache.put("https://x/", "ok", 200, "Summary", 1200, "fetched_html", "Src", "")
    path = next(tmp_path.glob("*.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["fetched_at"] = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    path.write_text(json.dumps(data), encoding="utf-8")
    assert cache.get("https://x/") is None


def test_cache_failure_uses_backoff(tmp_path):
    cache = ArticleCache(tmp_path, failure_backoff_hours=24)
    cache.put("https://x/", "http_error", 500, "", 0, "fetched_html", "Src", "boom")
    assert cache.get("https://x/") is not None

    path = next(tmp_path.glob("*.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["fetched_at"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    path.write_text(json.dumps(data), encoding="utf-8")
    assert cache.get("https://x/") is None


def test_cache_corrupt_json_is_miss(tmp_path):
    cache = ArticleCache(tmp_path)
    cache.put("https://x/", "ok", 200, "Summary", 1200, "fetched_html", "Src", "")
    next(tmp_path.glob("*.json")).write_text("{bad", encoding="utf-8")
    assert cache.get("https://x/") is None


def test_cache_without_current_version_is_miss(tmp_path):
    cache = ArticleCache(tmp_path)
    cache.put("https://x/", "ok", 200, "Summary", 1200, "fetched_html", "Src", "")
    path = next(tmp_path.glob("*.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("cache_version")
    path.write_text(json.dumps(data), encoding="utf-8")
    assert cache.get("https://x/") is None


def test_cache_prune_removes_stale_entries(tmp_path):
    cache = ArticleCache(tmp_path, ttl_days=30)
    cache.put("https://fresh/", "ok", 200, "Fresh", 1200, "rss_body", "Src", "")
    cache.put("https://stale/", "ok", 200, "Stale", 1200, "rss_body", "Src", "")
    for path in tmp_path.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["url"] == "https://stale/":
            data["fetched_at"] = (
                datetime.now(timezone.utc) - timedelta(days=31)
            ).isoformat()
            path.write_text(json.dumps(data), encoding="utf-8")
    assert cache.prune() == 1
    assert cache.get("https://fresh/") is not None
    assert cache.get("https://stale/") is None
