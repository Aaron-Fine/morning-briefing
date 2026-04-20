"""Tests for article extraction helpers."""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sources.article_extract import extract_article


def test_extract_article_returns_ok_for_full_article():
    with patch(
        "sources.article_extract.trafilatura.extract",
        return_value="This is article content with useful facts. " * 40,
    ):
        result = extract_article("<html></html>", min_body_chars=300)
    assert result.status == "ok"
    assert result.raw_length >= 300


def test_extract_article_returns_failed_for_empty_html():
    result = extract_article("", min_body_chars=300)
    assert result.status == "extraction_failed"
    assert result.text == ""


def test_extract_article_classifies_short_subscribe_text_as_paywall():
    with patch(
        "sources.article_extract.trafilatura.extract",
        return_value="Subscribe to read the full article.",
    ):
        result = extract_article("<html></html>", min_body_chars=300)
    assert result.status == "paywall"


def test_extract_article_respects_min_body_chars():
    with patch(
        "sources.article_extract.trafilatura.extract",
        return_value="Short body. " * 10,
    ):
        assert extract_article("<html></html>", min_body_chars=500).status == "extraction_failed"
        assert extract_article("<html></html>", min_body_chars=50).status == "ok"
