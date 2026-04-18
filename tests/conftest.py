"""Shared test fixtures and configuration."""

import pytest


@pytest.fixture
def sample_rss_item():
    """A well-formed RSS item for testing."""
    return {
        "url": "https://example.com/article-1",
        "title": "Test Article Title",
        "summary": "This is a test summary of the article.",
        "category": "ai-tech",
        "source": "Example Feed",
    }


@pytest.fixture
def sample_local_news_item():
    """A genuine local news item."""
    return {
        "url": "https://www.cachevalleydaily.com/news/some-local-event",
        "title": "Local City Council Meeting",
        "summary": "Cache Valley city council discussed zoning changes.",
    }


@pytest.fixture
def sample_press_release_item():
    """A syndicated press release that should be filtered out."""
    return {
        "url": "https://www.hjnews.com/press_releases/some-pr",
        "title": "Company Announces Product",
        "summary": "PRNewswire — A company announced something today.",
    }


@pytest.fixture
def sample_config():
    """Minimal config dict for testing stages."""
    return {
        "location": {
            "city": "Logan",
            "state": "UT",
            "latitude": 41.737,
            "longitude": -111.834,
        },
        "digest": {
            "local": {"max_items": 4},
            "at_a_glance": {"min_items": 6, "max_items": 14},
        },
    }


@pytest.fixture
def sample_raw_sources(sample_rss_item, sample_local_news_item):
    """Minimal raw_sources dict for testing validation."""
    return {
        "rss": [sample_rss_item],
        "local_news": [sample_local_news_item],
        "analysis_transcripts": [],
    }
