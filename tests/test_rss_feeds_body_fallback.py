"""Tests for RSS body-field fallback."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sources.rss_feeds import _entry_body


def test_entry_body_prefers_content_over_teaser_summary():
    entry = {
        "summary": "Short teaser",
        "description": "Description",
        "content": [{"value": "Full content body"}],
    }
    assert _entry_body(entry) == "Full content body"


def test_entry_body_falls_back_to_summary():
    assert _entry_body({"summary": "Summary", "content": []}) == "Summary"


def test_entry_body_falls_back_to_description():
    assert _entry_body({"summary": "", "description": "Description"}) == "Description"


def test_entry_body_returns_empty_when_all_blank():
    assert _entry_body({"summary": " ", "content": [{"value": ""}]}) == ""
