"""Tests for utils/urls.py — URL collection and domain extraction."""

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.urls import collect_known_urls, extract_domains


class TestCollectKnownUrls:
    """Tests for collect_known_urls function."""

    def test_collects_from_rss(self):
        raw_sources = {
            "rss": [
                {"url": "https://example.com/1"},
                {"url": "https://example.com/2"},
            ],
            "local_news": [],
            "analysis_transcripts": [],
        }
        result = collect_known_urls(raw_sources)
        assert result == {"https://example.com/1", "https://example.com/2"}

    def test_collects_from_local_news(self):
        raw_sources = {
            "rss": [],
            "local_news": [
                {"url": "https://local.com/1"},
            ],
            "analysis_transcripts": [],
        }
        result = collect_known_urls(raw_sources)
        assert "https://local.com/1" in result

    def test_collects_from_analysis_transcripts(self):
        raw_sources = {
            "rss": [],
            "local_news": [],
            "analysis_transcripts": [
                {"url": "https://youtube.com/watch?v=abc123"},
            ],
        }
        result = collect_known_urls(raw_sources)
        assert "https://youtube.com/watch?v=abc123" in result

    def test_collects_from_all_sources(self):
        raw_sources = {
            "rss": [{"url": "https://rss.com/1"}],
            "local_news": [{"url": "https://local.com/1"}],
            "analysis_transcripts": [{"url": "https://yt.com/1"}],
        }
        result = collect_known_urls(raw_sources)
        assert len(result) == 3
        assert "https://rss.com/1" in result
        assert "https://local.com/1" in result
        assert "https://yt.com/1" in result

    def test_skips_items_without_url(self):
        raw_sources = {
            "rss": [
                {"url": "https://example.com/1"},
                {"title": "No URL here"},
                {},
            ],
            "local_news": [],
            "analysis_transcripts": [],
        }
        result = collect_known_urls(raw_sources)
        assert result == {"https://example.com/1"}

    def test_skips_items_with_empty_url(self):
        raw_sources = {
            "rss": [{"url": ""}],
            "local_news": [],
            "analysis_transcripts": [],
        }
        result = collect_known_urls(raw_sources)
        assert "" not in result
        assert result == set()

    def test_empty_raw_sources_returns_empty_set(self):
        result = collect_known_urls({})
        assert result == set()

    def test_none_values_in_lists(self):
        raw_sources = {
            "rss": [None, {"url": "https://ok.com"}],
            "local_news": [None],
            "analysis_transcripts": [],
        }
        with pytest.raises(AttributeError):
            collect_known_urls(raw_sources)

    def test_deduplicates_urls(self):
        raw_sources = {
            "rss": [
                {"url": "https://example.com/1"},
                {"url": "https://example.com/1"},
            ],
            "local_news": [{"url": "https://example.com/1"}],
            "analysis_transcripts": [],
        }
        result = collect_known_urls(raw_sources)
        assert len(result) == 1
        assert result == {"https://example.com/1"}

    def test_domain_analysis_collects_from_links(self):
        raw_sources = {
            "rss": [],
            "local_news": [],
            "analysis_transcripts": [],
        }
        domain_analysis = {
            "geopolitics": {
                "items": [
                    {
                        "links": [
                            {"url": "https://domain.com/1", "label": "Source 1"},
                            {"url": "https://domain.com/2", "label": "Source 2"},
                        ]
                    }
                ]
            },
            "ai_tech": {
                "items": [
                    {
                        "links": [
                            {"url": "https://ai.com/1", "label": "AI Source"},
                        ]
                    }
                ]
            },
        }
        result = collect_known_urls(raw_sources, domain_analysis)
        assert len(result) == 3
        assert "https://domain.com/1" in result
        assert "https://domain.com/2" in result
        assert "https://ai.com/1" in result

    def test_domain_analysis_skips_non_dict_results(self):
        raw_sources = {"rss": [], "local_news": [], "analysis_transcripts": []}
        domain_analysis = {
            "geopolitics": "not a dict",
            "ai_tech": {"items": [{"links": [{"url": "https://ai.com/1"}]}]},
        }
        result = collect_known_urls(raw_sources, domain_analysis)
        assert result == {"https://ai.com/1"}

    def test_domain_analysis_skips_items_without_links(self):
        raw_sources = {"rss": [], "local_news": [], "analysis_transcripts": []}
        domain_analysis = {
            "geopolitics": {
                "items": [
                    {"headline": "No links here"},
                    {"links": []},
                ]
            }
        }
        result = collect_known_urls(raw_sources, domain_analysis)
        assert result == set()

    def test_domain_analysis_skips_links_without_url(self):
        raw_sources = {"rss": [], "local_news": [], "analysis_transcripts": []}
        domain_analysis = {
            "geopolitics": {
                "items": [
                    {
                        "links": [
                            {"label": "No URL"},
                            {"url": "https://ok.com"},
                        ]
                    }
                ]
            }
        }
        result = collect_known_urls(raw_sources, domain_analysis)
        assert result == {"https://ok.com"}

    def test_domain_analysis_none_skipped(self):
        raw_sources = {"rss": [], "local_news": [], "analysis_transcripts": []}
        domain_analysis = None
        result = collect_known_urls(raw_sources, domain_analysis)
        assert result == set()


class TestExtractDomains:
    """Tests for extract_domains function."""

    def test_extracts_domain_from_url(self):
        urls = {"https://example.com/path/to/page"}
        result = extract_domains(urls)
        assert result == {"example.com"}

    def test_extracts_multiple_domains(self):
        urls = {
            "https://example.com/page",
            "https://news.example.org/article",
            "http://api.test.io/v1/data",
        }
        result = extract_domains(urls)
        assert result == {"example.com", "news.example.org", "api.test.io"}

    def test_deduplicates_domains(self):
        urls = {
            "https://example.com/page1",
            "https://example.com/page2",
            "https://example.com/page3",
        }
        result = extract_domains(urls)
        assert result == {"example.com"}

    def test_empty_set_returns_empty_set(self):
        assert extract_domains(set()) == set()

    def test_skips_invalid_urls(self):
        urls = {"not-a-url", "", "ftp://files.example.com/doc"}
        result = extract_domains(urls)
        assert "not-a-url" not in result
        assert "" not in result
        assert "files.example.com" in result

    def test_handles_url_with_port(self):
        urls = {"https://example.com:8080/api"}
        result = extract_domains(urls)
        assert result == {"example.com:8080"}

    def test_handles_url_with_subdomain(self):
        urls = {"https://sub.domain.example.com/page"}
        result = extract_domains(urls)
        assert result == {"sub.domain.example.com"}
