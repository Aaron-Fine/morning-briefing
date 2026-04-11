"""Tests for stages/assemble.py — template rendering and digest assembly."""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from stages.assemble import (
    _item_to_glance,
    _domain_item_to_deep_dive,
    _build_from_domain_analysis,
    _extract_peripheral_data,
    run,
)


class TestItemToGlance:
    def test_basic_fields(self):
        item = {
            "tag": "war",
            "headline": "Test headline",
            "facts": "Test facts",
            "analysis": "Test analysis",
        }
        result = _item_to_glance(item)
        assert result["tag"] == "war"
        assert result["tag_label"] == "Conflict"
        assert result["headline"] == "Test headline"
        assert result["facts"] == "Test facts"
        assert result["analysis"] == "Test analysis"
        assert result["links"] == []
        assert result["source_depth"] == ""
        assert result["connection_hooks"] == []

    def test_cross_domain_note_in_context(self):
        item = {
            "tag": "tech",
            "facts": "F",
            "analysis": "A",
            "cross_domain_note": "Note",
        }
        result = _item_to_glance(item)
        assert result["cross_domain_note"] == "Note"
        assert "F" in result["context"]
        assert "A" in result["context"]
        assert "(Note)" in result["context"]

    def test_missing_fields_defaults(self):
        result = _item_to_glance({})
        assert result["tag"] == ""
        assert result["tag_label"] == ""
        assert result["headline"] == ""
        assert result["context"] == ""

    def test_tag_label_fallback(self):
        item = {"tag": "unknown"}
        result = _item_to_glance(item)
        assert result["tag_label"] == "Unknown"

    def test_tag_label_from_item(self):
        item = {"tag": "war", "tag_label": "Custom Label"}
        result = _item_to_glance(item)
        assert result["tag_label"] == "Custom Label"


class TestDomainItemToDeepDive:
    def test_basic_conversion(self):
        item = {
            "headline": "Dive headline",
            "facts": "Facts",
            "analysis": "Analysis",
            "deep_dive_rationale": "Rationale",
            "links": [{"url": "https://example.com", "label": "Source"}],
            "source_depth": "widely-reported",
        }
        result = _domain_item_to_deep_dive(item)
        assert result["headline"] == "Dive headline"
        assert "<p>Facts</p>" in result["body"]
        assert "<p>Analysis</p>" in result["body"]
        assert result["why_it_matters"] == "Rationale"
        assert result["further_reading"] == item["links"]
        assert result["source_depth"] == "widely-reported"

    def test_empty_item(self):
        result = _domain_item_to_deep_dive({})
        assert result["body"] == ""
        assert result["why_it_matters"] == ""


class TestBuildFromDomainAnalysis:
    def test_empty_domain_analysis(self):
        context = {"domain_analysis": {}}
        config = {"digest": {"at_a_glance": {"max_items": 7, "normal_items": 5}}}
        at_a_glance, deep_dives, market = _build_from_domain_analysis(context, config)
        assert at_a_glance == []
        assert deep_dives == []
        assert market == ""

    def test_items_sorted_by_depth(self):
        context = {
            "domain_analysis": {
                "geopolitics": {
                    "items": [
                        {"headline": "Single", "source_depth": "single-source"},
                        {"headline": "Wide", "source_depth": "widely-reported"},
                        {"headline": "Corroborated", "source_depth": "corroborated"},
                    ]
                }
            }
        }
        config = {"digest": {"at_a_glance": {"max_items": 10, "normal_items": 10}}}
        at_a_glance, _, _ = _build_from_domain_analysis(context, config)
        assert at_a_glance[0]["headline"] == "Wide"
        assert at_a_glance[1]["headline"] == "Corroborated"
        assert at_a_glance[2]["headline"] == "Single"

    def test_deep_dive_candidates_separated(self):
        context = {
            "domain_analysis": {
                "defense_space": {
                    "items": [
                        {"headline": "Normal", "deep_dive_candidate": False},
                        {"headline": "Dive", "deep_dive_candidate": True},
                    ]
                }
            }
        }
        config = {"digest": {"at_a_glance": {"max_items": 10, "normal_items": 10}}}
        at_a_glance, deep_dives, _ = _build_from_domain_analysis(context, config)
        assert len(at_a_glance) == 1
        assert at_a_glance[0]["headline"] == "Normal"
        assert len(deep_dives) == 1
        assert deep_dives[0]["headline"] == "Dive"

    def test_market_context_from_econ(self):
        context = {
            "domain_analysis": {
                "econ": {"market_context": "Market is volatile"},
                "geopolitics": {"items": []},
            }
        }
        config = {"digest": {"at_a_glance": {"max_items": 7, "normal_items": 5}}}
        _, _, market = _build_from_domain_analysis(context, config)
        assert market == "Market is volatile"

    def test_at_a_glance_cap_enforced(self):
        items = [{"headline": f"Item {i}"} for i in range(15)]
        context = {"domain_analysis": {"geopolitics": {"items": items}}}
        config = {"digest": {"at_a_glance": {"max_items": 7, "normal_items": 10}}}
        at_a_glance, _, _ = _build_from_domain_analysis(context, config)
        assert len(at_a_glance) == 7


class TestExtractPeripheralData:
    def test_context_takes_priority(self):
        context = {
            "spiritual": {"reflection": "From context"},
            "weather": {"temp": 72},
            "weather_html": "<svg>...</svg>",
            "calendar": {"events": [{"name": "Event"}]},
            "local_items": [{"headline": "Local"}],
        }
        raw_sources = {
            "come_follow_me": {"scripture_text": "From raw"},
            "weather": {"temp": 0},
            "local_news": [{"headline": "Raw"}],
        }
        result = _extract_peripheral_data(context, raw_sources)
        assert result["spiritual"]["reflection"] == "From context"
        assert result["weather"]["temp"] == 72
        assert result["weather_html"] == "<svg>...</svg>"
        assert result["week_ahead"] == [{"name": "Event"}]
        assert result["local_items"] == [{"headline": "Local"}]

    def test_fallback_to_raw_sources(self):
        context = {}
        raw_sources = {
            "come_follow_me": {"scripture_text": "Scripture"},
            "weather": {"temp": 65},
            "local_news": [{"headline": "Raw"}],
        }
        result = _extract_peripheral_data(context, raw_sources)
        assert result["spiritual"]["reflection"] == "Scripture"
        assert result["weather"]["temp"] == 65
        assert result["local_items"] == [{"headline": "Raw"}]


class TestAssembleRun:
    def _make_context(self, **overrides):
        context = {
            "cross_domain_output": {
                "at_a_glance": [
                    {
                        "tag": "war",
                        "headline": "Test",
                        "facts": "F",
                        "analysis": "A",
                        "links": [],
                    }
                ],
                "deep_dives": [
                    {
                        "headline": "Dive",
                        "body": "<p>Body</p>",
                        "why_it_matters": "WM",
                        "further_reading": [],
                        "source_depth": "widely-reported",
                    }
                ],
                "market_context": "Markets up",
                "worth_reading": [],
                "cross_domain_connections": [],
            },
            "seam_data": {
                "contested_narratives": [],
                "coverage_gaps": [],
                "key_assumptions": [],
            },
            "raw_sources": {"rss": [], "local_news": [], "markets": []},
            "calendar": {"events": []},
            "weather": {},
            "spiritual": None,
        }
        context.update(overrides)
        return context

    def _make_config(self):
        return {
            "digest": {"at_a_glance": {"max_items": 7, "normal_items": 5}},
            "rss": {"feeds": []},
            "local_news": {"sources": []},
            "youtube": {"analysis_channels": []},
            "location": {"timezone": "America/Denver"},
        }

    def test_phase3_mode(self):
        result = run(self._make_context(), self._make_config())
        assert "html" in result
        assert "template_data" in result
        assert "digest_json" in result
        assert len(result["template_data"]["at_a_glance"]) == 1
        assert len(result["template_data"]["deep_dives"]) == 1

    def test_phase1_mode(self):
        context = self._make_context()
        del context["cross_domain_output"]
        context["domain_analysis"] = {
            "geopolitics": {
                "items": [
                    {
                        "tag": "war",
                        "headline": "Phase1",
                        "facts": "F",
                        "analysis": "A",
                    }
                ]
            }
        }
        result = run(context, self._make_config())
        assert "html" in result
        assert len(result["template_data"]["at_a_glance"]) == 1

    def test_empty_fallback(self):
        context = {"seam_data": {}, "raw_sources": {}}
        result = run(context, self._make_config())
        assert "html" in result
        assert result["template_data"]["at_a_glance"] == []

    def test_deep_dive_body_is_markup(self):
        from markupsafe import Markup

        result = run(self._make_context(), self._make_config())
        dive = result["template_data"]["deep_dives"][0]
        assert isinstance(dive["body"], Markup)

    def test_digest_json_has_plain_string_body(self):
        from markupsafe import Markup

        result = run(self._make_context(), self._make_config())
        dive = result["digest_json"]["deep_dives"][0]
        assert isinstance(dive["body"], str)
        assert not isinstance(dive["body"], Markup)

    def test_weather_html_marked_safe(self):
        from markupsafe import Markup

        context = self._make_context(weather_html="<svg>test</svg>")
        result = run(context, self._make_config())
        assert isinstance(result["template_data"]["weather_html"], Markup)

    def test_source_names_in_template(self):
        config = self._make_config()
        config["rss"]["feeds"] = [{"name": "Test Feed"}]
        config["local_news"]["sources"] = [{"name": "Local"}]
        config["youtube"]["analysis_channels"] = [{"name": "YT"}]
        result = run(self._make_context(), config)
        assert "Test Feed" in result["template_data"]["rss_source_names"]
        assert "Local" in result["template_data"]["rss_source_names"]
        assert "YT" in result["template_data"]["yt_source_names"]

    def test_cross_domain_connections_in_digest_json(self):
        context = self._make_context()
        context["cross_domain_output"]["cross_domain_connections"] = [
            {"description": "Test connection"}
        ]
        result = run(context, self._make_config())
        assert result["digest_json"]["cross_domain_connections"] == [
            {"description": "Test connection"}
        ]
