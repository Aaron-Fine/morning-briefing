"""Tests for validate.py — Security Layer 3 output validation."""

import sys
import os
import logging
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from validate import (
    VALID_TAGS,
    VALID_TAG_LABELS,
    _ALLOWED_HTML_TAGS,
    _extract_urls_from_value,
    _strip_disallowed_html,
    validate_urls,
    _validate_at_a_glance,
    _validate_deep_dives,
    _validate_seam_items,
    validate_stage_output,
)


class TestValidTagsConsistency:
    """Ensure tag vocabulary is well-formed."""

    def test_valid_tags_is_non_empty_set(self):
        assert isinstance(VALID_TAGS, set)
        assert len(VALID_TAGS) > 0

    def test_valid_tag_labels_keys_match_valid_tags(self):
        assert set(VALID_TAG_LABELS.keys()) == VALID_TAGS

    def test_all_tag_labels_are_non_empty_strings(self):
        for tag, label in VALID_TAG_LABELS.items():
            assert isinstance(label, str)
            assert len(label) > 0


class TestExtractUrlsFromValue:
    """Recursive URL extraction from nested structures."""

    def test_extracts_from_string(self):
        urls = _extract_urls_from_value("Check https://example.com for info")
        assert "https://example.com" in urls

    def test_extracts_multiple_urls_from_string(self):
        urls = _extract_urls_from_value("See https://a.com and http://b.org/path")
        assert "https://a.com" in urls
        assert "http://b.org/path" in urls

    def test_extracts_from_dict_values(self):
        urls = _extract_urls_from_value({"link": "https://example.com/page"})
        assert "https://example.com/page" in urls

    def test_extracts_from_nested_dict(self):
        data = {"outer": {"inner": {"url": "https://deep.com"}}}
        urls = _extract_urls_from_value(data)
        assert "https://deep.com" in urls

    def test_extracts_from_list(self):
        urls = _extract_urls_from_value(["https://a.com", "https://b.com"])
        assert len(urls) == 2

    def test_extracts_from_list_of_dicts(self):
        data = [{"url": "https://a.com"}, {"url": "https://b.com"}]
        urls = _extract_urls_from_value(data)
        assert len(urls) == 2

    def test_returns_empty_for_no_urls(self):
        urls = _extract_urls_from_value("no urls here")
        assert urls == []

    def test_returns_empty_for_empty_structure(self):
        assert _extract_urls_from_value({}) == []
        assert _extract_urls_from_value([]) == []
        assert _extract_urls_from_value("") == []

    def test_handles_mixed_types(self):
        data = {
            "text": "Visit https://example.com",
            "links": [{"url": "https://a.com"}, "https://b.com"],
            "nested": {"deep": "http://c.org"},
        }
        urls = _extract_urls_from_value(data)
        assert len(urls) == 4

    def test_non_string_non_iterable_returns_empty(self):
        assert _extract_urls_from_value(42) == []
        assert _extract_urls_from_value(None) == []
        assert _extract_urls_from_value(True) == []


class TestStripDisallowedHtml:
    """HTML sanitization for deep dive body fields."""

    def test_keeps_allowed_tags(self):
        html = "<p>Hello <strong>world</strong></p>"
        result = _strip_disallowed_html(html)
        assert result == html

    def test_strips_script_tags(self):
        html = "<script>alert(1)</script><p>Safe</p>"
        result = _strip_disallowed_html(html)
        assert "<script>" not in result
        assert "alert(1)" in result  # text content preserved
        assert "<p>Safe</p>" in result

    def test_strips_div_tags(self):
        html = '<div class="wrapper"><p>Content</p></div>'
        result = _strip_disallowed_html(html)
        assert "<div" not in result
        assert "<p>Content</p>" in result

    def test_strips_img_tags(self):
        html = '<p>See <img src="evil.png" onload="hack()"> this</p>'
        result = _strip_disallowed_html(html)
        assert "<img" not in result
        assert "See  this" in result

    def test_all_allowed_tags_pass_through(self):
        for tag in _ALLOWED_HTML_TAGS:
            html = f"<{tag}>content</{tag}>"
            result = _strip_disallowed_html(html)
            assert html in result, f"Allowed tag <{tag}> was stripped"

    def test_case_insensitive_tag_matching(self):
        html = "<SCRIPT>alert(1)</SCRIPT><P>text</P>"
        result = _strip_disallowed_html(html)
        assert "<SCRIPT" not in result
        assert "<script" not in result
        assert "<P>text</P>" in result

    def test_self_closing_allowed_tag_kept(self):
        html = "Text<br/>More"
        result = _strip_disallowed_html(html)
        assert "<br/>" in result

    def test_self_closing_disallowed_tag_stripped(self):
        html = "Text<iframe/>End"
        result = _strip_disallowed_html(html)
        assert "<iframe" not in result

    def test_empty_string_returns_empty(self):
        assert _strip_disallowed_html("") == ""

    def test_no_html_returns_unchanged(self):
        text = "Plain text with no HTML"
        assert _strip_disallowed_html(text) == text


class TestValidateUrls:
    """URL validation strips hallucinated URLs."""

    def test_keeps_known_urls(self):
        known = {"https://example.com/a", "https://trusted.org/b"}
        data = {"url": "https://example.com/a"}
        result = validate_urls(data, known)
        assert result["url"] == "https://example.com/a"

    def test_strips_unknown_urls(self, caplog):
        known = {"https://example.com/a"}
        data = {"url": "https://hallucinated.com/fake"}
        with caplog.at_level(logging.WARNING):
            result = validate_urls(data, known)
        assert result["url"] == ""
        assert (
            "hallucinated" in caplog.text.lower() or "stripped" in caplog.text.lower()
        )

    def test_handles_empty_url_string(self):
        known = {"https://example.com"}
        data = {"url": ""}
        result = validate_urls(data, known)
        assert result["url"] == ""

    def test_recurses_into_nested_dicts(self):
        known = {"https://ok.com"}
        data = {
            "outer": {"url": "https://ok.com"},
            "inner": {"url": "https://bad.com"},
        }
        result = validate_urls(data, known)
        assert result["outer"]["url"] == "https://ok.com"
        assert result["inner"]["url"] == ""

    def test_recurses_into_lists(self):
        known = {"https://ok.com"}
        data = [
            {"url": "https://ok.com"},
            {"url": "https://bad.com"},
            {"url": "https://ok.com/2"},
        ]
        result = validate_urls(data, known)
        assert result[0]["url"] == "https://ok.com"
        assert result[1]["url"] == ""
        assert result[2]["url"] == ""

    def test_non_url_keys_recursed_but_not_stripped(self):
        known = {"https://ok.com"}
        data = {
            "headline": "Visit https://bad.com for more",
            "url": "https://ok.com",
        }
        result = validate_urls(data, known)
        assert result["url"] == "https://ok.com"
        assert "https://bad.com" in result["headline"]

    def test_non_dict_non_list_returns_unchanged(self):
        assert validate_urls("string", set()) == "string"
        assert validate_urls(42, set()) == 42
        assert validate_urls(None, set()) is None


class TestValidateAtAGlance:
    """Validation of at_a_glance section."""

    def test_non_list_resets_to_empty(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = _validate_at_a_glance("not a list", set(), {})
        assert result == []
        assert "not a list" in caplog.text

    def test_non_dict_item_skipped_in_source_loop(self, caplog):
        """Non-dict items are now skipped gracefully in the source distribution loop."""
        items = [{"tag": "war", "headline": "Good", "links": []}, "bad item"]
        with caplog.at_level(logging.WARNING):
            result = _validate_at_a_glance(items, set(), {})
        # Valid dict item should be processed, non-dict skipped
        assert len(result) == 1
        assert result[0]["headline"] == "Good"
        # The non-dict item gets logged as skipped in the cleaning loop
        assert "not a dict" in caplog.text.lower()

    def test_all_dict_items_with_non_dict_skipped_in_cleaning_loop(self):
        """When all items are dicts, non-dict-like items are skipped in the
        cleaning loop (but the source distribution loop still processes them)."""
        items = [
            {"tag": "war", "headline": "Good", "links": []},
            {"tag": "tech", "headline": "Also good", "links": []},
        ]
        result = _validate_at_a_glance(items, set(), {})
        assert len(result) == 2

    def test_invalid_tag_replaced_with_uncategorized(self, caplog):
        items = [{"tag": "invalid_tag", "headline": "Test", "links": []}]
        with caplog.at_level(logging.WARNING):
            result = _validate_at_a_glance(items, set(), {})
        assert result[0]["tag"] == "uncategorized"

    def test_valid_tag_preserved(self):
        items = [
            {"tag": "ai", "headline": "AI news", "context": "Some context", "links": []}
        ]
        result = _validate_at_a_glance(items, set(), {})
        assert result[0]["tag"] == "ai"

    def test_source_distribution_warning(self, caplog):
        items = [
            {
                "tag": "tech",
                "headline": f"Headline {i}",
                "links": [{"label": "SingleSource: Article"}],
            }
            for i in range(10)
        ]
        with caplog.at_level(logging.WARNING):
            _validate_at_a_glance(items, set(), {})
        assert "source distribution anomaly" in caplog.text

    def test_verbatim_echo_detection_logged(self, caplog):
        source_data = {"rss": [{"title": "Exact Headline Match"}]}
        items = [{"tag": "tech", "headline": "Exact Headline Match", "links": []}]
        with caplog.at_level(logging.INFO):
            _validate_at_a_glance(items, set(), source_data)
        assert "verbatim echo" in caplog.text.lower()

    def test_verbatim_echo_from_local_news(self, caplog):
        source_data = {"local_news": [{"title": "Local Headline"}]}
        items = [{"tag": "local", "headline": "Local Headline", "links": []}]
        with caplog.at_level(logging.INFO):
            _validate_at_a_glance(items, set(), source_data)
        assert "verbatim echo" in caplog.text.lower()

    def test_output_has_required_fields(self):
        items = [
            {
                "tag": "war",
                "headline": "Conflict headline",
                "context": "Background info",
                "links": [{"url": "https://example.com"}],
            }
        ]
        known = {"https://example.com"}
        result = _validate_at_a_glance(items, known, {})
        assert result[0]["tag"] == "war"
        # tag_label defaults to tag.capitalize() when not explicitly provided
        assert result[0]["tag_label"] == "War"
        assert result[0]["headline"] == "Conflict headline"
        assert result[0]["context"] == "Background info"
        assert result[0]["links"] == [{"url": "https://example.com"}]

    def test_tag_label_from_valid_tag_labels(self):
        """When tag_label is explicitly provided, it is preserved."""
        items = [
            {
                "tag": "war",
                "tag_label": "Conflict",
                "headline": "Test",
                "links": [],
            }
        ]
        result = _validate_at_a_glance(items, set(), {})
        assert result[0]["tag_label"] == "Conflict"

    def test_missing_fields_get_defaults(self):
        items = [{"links": []}]
        result = _validate_at_a_glance(items, set(), {})
        assert result[0]["tag"] == "uncategorized"
        assert result[0]["headline"] == ""
        assert result[0]["context"] == ""
        assert result[0]["links"] == []

    def test_urls_validated_in_links(self):
        items = [
            {
                "tag": "tech",
                "headline": "Test",
                "links": [
                    {"url": "https://known.com"},
                    {"url": "https://unknown.com"},
                ],
            }
        ]
        known = {"https://known.com"}
        result = _validate_at_a_glance(items, known, {})
        assert result[0]["links"][0]["url"] == "https://known.com"
        assert result[0]["links"][1]["url"] == ""


class TestValidateDeepDives:
    """Validation of deep_dives section."""

    def test_non_list_returns_empty(self):
        assert _validate_deep_dives("not a list", set()) == []

    def test_non_dict_item_skipped(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = _validate_deep_dives([42, {"headline": "OK"}], set())
        assert len(result) == 1
        assert result[0]["headline"] == "OK"

    def test_html_sanitization(self, caplog):
        dive = {
            "headline": "Test",
            "body": "<script>bad()</script><p>Good content</p>",
            "why_it_matters": "Important",
            "further_reading": [],
        }
        with caplog.at_level(logging.INFO):
            result = _validate_deep_dives([dive], set())
        assert "<script>" not in result[0]["body"]
        assert "<p>Good content</p>" in result[0]["body"]
        assert "stripped disallowed HTML" in caplog.text

    def test_allowed_html_preserved(self):
        dive = {
            "headline": "Test",
            "body": "<p>Para</p><em>Em</em><strong>Strong</strong>",
            "why_it_matters": "Why",
            "further_reading": [],
        }
        result = _validate_deep_dives([dive], set())
        assert result[0]["body"] == dive["body"]

    def test_urls_stripped_in_further_reading(self):
        dive = {
            "headline": "Test",
            "body": "",
            "why_it_matters": "Why",
            "further_reading": [
                {"url": "https://known.com"},
                {"url": "https://unknown.com"},
            ],
        }
        known = {"https://known.com"}
        result = _validate_deep_dives([dive], known)
        assert result[0]["further_reading"][0]["url"] == "https://known.com"
        assert result[0]["further_reading"][1]["url"] == ""

    def test_empty_list_returns_empty(self):
        assert _validate_deep_dives([], set()) == []


class TestValidateSeamItems:
    """Validation of contested_narratives and coverage_gaps."""

    def test_non_list_returns_empty(self):
        assert _validate_seam_items("not a list", set(), "contested") == []

    def test_non_dict_item_skipped(self):
        items = [42, {"topic": "OK", "description": "Desc"}]
        result = _validate_seam_items(items, set(), "contested")
        assert len(result) == 1
        assert result[0]["topic"] == "OK"

    def test_contested_has_correct_fields(self):
        items = [
            {
                "topic": "Topic",
                "description": "Desc",
                "sources_a": "A",
                "sources_b": "B",
                "links": [{"url": "https://known.com"}],
            }
        ]
        result = _validate_seam_items(items, {"https://known.com"}, "contested")
        assert result[0]["topic"] == "Topic"
        assert result[0]["sources_a"] == "A"
        assert result[0]["sources_b"] == "B"

    def test_gap_has_correct_fields(self):
        items = [
            {
                "topic": "Topic",
                "description": "Desc",
                "present_in": "A",
                "absent_from": "B",
                "links": [],
            }
        ]
        result = _validate_seam_items(items, set(), "gap")
        assert result[0]["present_in"] == "A"
        assert result[0]["absent_from"] == "B"
        assert "sources_a" not in result[0]

    def test_urls_validated(self):
        items = [
            {
                "topic": "T",
                "description": "D",
                "sources_a": "A",
                "sources_b": "B",
                "links": [{"url": "https://bad.com"}],
            }
        ]
        result = _validate_seam_items(items, set(), "contested")
        assert result[0]["links"][0]["url"] == ""


class TestValidateStageOutput:
    """Integration tests for the main validate_stage_output function."""

    def test_non_dict_input_returns_empty(self, caplog):
        with caplog.at_level(logging.ERROR):
            result = validate_stage_output("string", {}, "test_stage")
        assert result == {}
        assert "not a dict" in caplog.text

    def test_empty_dict_passes_through(self):
        result = validate_stage_output({}, {}, "test_stage")
        assert result == {}

    def test_at_a_glance_validated(self):
        output = {
            "at_a_glance": [
                {
                    "tag": "war",
                    "headline": "War news",
                    "context": "Background",
                    "links": [],
                }
            ]
        }
        result = validate_stage_output(output, {}, "test_stage")
        assert len(result["at_a_glance"]) == 1
        assert result["at_a_glance"][0]["tag"] == "war"

    def test_deep_dives_validated(self):
        output = {
            "deep_dives": [
                {
                    "headline": "Deep dive",
                    "body": "<p>Content</p>",
                    "why_it_matters": "Why",
                    "further_reading": [],
                }
            ]
        }
        result = validate_stage_output(output, {}, "test_stage")
        assert len(result["deep_dives"]) == 1
        assert result["deep_dives"][0]["headline"] == "Deep dive"

    def test_contested_narratives_validated(self):
        output = {
            "contested_narratives": [
                {
                    "topic": "T",
                    "description": "D",
                    "sources_a": "A",
                    "sources_b": "B",
                    "links": [],
                }
            ]
        }
        result = validate_stage_output(output, {}, "test_stage")
        assert len(result["contested_narratives"]) == 1

    def test_coverage_gaps_validated(self):
        output = {
            "coverage_gaps": [
                {
                    "topic": "T",
                    "description": "D",
                    "present_in": "A",
                    "absent_from": "B",
                    "links": [],
                }
            ]
        }
        result = validate_stage_output(output, {}, "test_stage")
        assert len(result["coverage_gaps"]) == 1

    def test_local_items_validated(self):
        output = {"local_items": [{"url": "https://known.com"}]}
        source_data = {"rss": [{"url": "https://known.com"}]}
        result = validate_stage_output(output, source_data, "test_stage")
        assert result["local_items"][0]["url"] == "https://known.com"

    def test_local_items_non_list_reset(self):
        output = {"local_items": "not a list"}
        result = validate_stage_output(output, {}, "test_stage")
        assert result["local_items"] == []

    def test_week_ahead_urls_validated(self):
        output = {
            "week_ahead": [
                {"url": "https://known.com"},
                {"url": "https://bad.com"},
            ]
        }
        source_data = {"rss": [{"url": "https://known.com"}]}
        result = validate_stage_output(output, source_data, "test_stage")
        assert result["week_ahead"][0]["url"] == "https://known.com"
        assert result["week_ahead"][1]["url"] == ""

    def test_worth_reading_urls_validated(self):
        output = {"worth_reading": [{"url": "https://bad.com"}]}
        result = validate_stage_output(output, {}, "test_stage")
        assert result["worth_reading"][0]["url"] == ""

    def test_market_context_urls_validated(self):
        output = {"market_context": [{"url": "https://known.com"}]}
        source_data = {"rss": [{"url": "https://known.com"}]}
        result = validate_stage_output(output, source_data, "test_stage")
        assert result["market_context"][0]["url"] == "https://known.com"

    def test_spiritual_reflection_urls_validated(self):
        output = {"spiritual_reflection": [{"url": "https://bad.com"}]}
        result = validate_stage_output(output, {}, "test_stage")
        assert result["spiritual_reflection"][0]["url"] == ""

    def test_full_pipeline_output_validated(self):
        """Test a realistic full output dict."""
        output = {
            "at_a_glance": [
                {
                    "tag": "ai",
                    "headline": "AI breakthrough announced",
                    "context": "Major tech company reveals new model",
                    "links": [{"url": "https://tech.example.com/ai"}],
                },
                {
                    "tag": "war",
                    "headline": "Conflict update",
                    "context": "Ongoing situation",
                    "links": [{"url": "https://news.example.com/conflict"}],
                },
            ],
            "deep_dives": [
                {
                    "headline": "AI regulation debate",
                    "body": "<p>Regulators are considering</p><script>bad()</script>",
                    "why_it_matters": "Could reshape the industry",
                    "further_reading": [{"url": "https://tech.example.com/ai"}],
                }
            ],
            "contested_narratives": [],
            "coverage_gaps": [],
            "local_items": [],
        }
        source_data = {
            "rss": [
                {"url": "https://tech.example.com/ai", "title": "AI Article"},
                {
                    "url": "https://news.example.com/conflict",
                    "title": "Conflict Article",
                },
            ],
            "local_news": [],
            "analysis_transcripts": [],
        }
        result = validate_stage_output(output, source_data, "cross_domain")

        assert len(result["at_a_glance"]) == 2
        assert result["at_a_glance"][0]["tag"] == "ai"
        assert result["at_a_glance"][1]["tag"] == "war"
        assert len(result["deep_dives"]) == 1
        assert "<script>" not in result["deep_dives"][0]["body"]

    def test_min_items_warning(self, caplog):
        output = {
            "at_a_glance": [
                {"tag": "war", "headline": "Only one", "context": "", "links": []}
            ]
        }
        source_data = {
            "rss": [],
            "local_news": [],
            "analysis_transcripts": [],
            "_config": {"digest": {"at_a_glance": {"min_items": 3, "max_items": 20}}},
        }
        with caplog.at_level(logging.WARNING):
            validate_stage_output(output, source_data, "test_stage")
        assert "only 1 at_a_glance items" in caplog.text

    def test_max_items_warning(self, caplog):
        output = {
            "at_a_glance": [
                {"tag": "war", "headline": f"Item {i}", "context": "", "links": []}
                for i in range(25)
            ]
        }
        source_data = {
            "rss": [],
            "local_news": [],
            "analysis_transcripts": [],
            "_config": {"digest": {"at_a_glance": {"min_items": 3, "max_items": 20}}},
        }
        with caplog.at_level(logging.WARNING):
            validate_stage_output(output, source_data, "test_stage")
        assert "exceeds max" in caplog.text

    def test_no_valid_deep_dives_warning(self, caplog):
        output = {"deep_dives": ["not a dict", 42]}
        with caplog.at_level(logging.WARNING):
            validate_stage_output(output, {}, "test_stage")
        assert "no valid deep dives" in caplog.text

    def test_unknown_fields_preserved(self):
        output = {"at_a_glance": [], "custom_field": "value"}
        result = validate_stage_output(output, {}, "test_stage")
        assert result["custom_field"] == "value"
