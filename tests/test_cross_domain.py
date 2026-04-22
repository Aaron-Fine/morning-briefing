"""Tests for stages/cross_domain.py."""

import sys
import os
import json
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.cross_domain import (
    _normalize_tag,
    _build_input,
    _empty_output,
    _VALID_TAGS,
    _TAG_LABELS,
    _TAG_KEYWORDS,
    run,
)


class TestNormalizeTag:
    def test_exact_match_valid_tag(self):
        assert _normalize_tag("war") == "war"
        assert _normalize_tag("ai") == "ai"
        assert _normalize_tag("defense") == "defense"
        assert _normalize_tag("space") == "space"
        assert _normalize_tag("tech") == "tech"
        assert _normalize_tag("econ") == "econ"
        assert _normalize_tag("cyber") == "cyber"
        assert _normalize_tag("local") == "local"
        assert _normalize_tag("science") == "science"
        assert _normalize_tag("domestic") == "domestic"

    def test_case_insensitive(self):
        assert _normalize_tag("WAR") == "war"
        assert _normalize_tag("Ai") == "ai"
        assert _normalize_tag("Defense") == "defense"

    def test_keyword_matching_war(self):
        assert _normalize_tag("ukraine conflict") == "war"
        assert _normalize_tag("russia military") == "war"
        assert _normalize_tag("iran missile strike") == "war"
        assert _normalize_tag("nato troops") == "war"

    def test_keyword_matching_defense(self):
        assert _normalize_tag("pentagon f-35") == "defense"
        assert _normalize_tag("dod procurement") == "defense"

    def test_keyword_matching_space(self):
        assert _normalize_tag("nasa lunar orbit") == "space"
        assert _normalize_tag("satellite launch") == "space"

    def test_keyword_matching_ai(self):
        assert _normalize_tag("openai llm model") == "ai"
        assert _normalize_tag("artificial intelligence") == "ai"

    def test_keyword_matching_tech(self):
        assert _normalize_tag("github open source") == "tech"

    def test_keyword_matching_cyber(self):
        assert _normalize_tag("cybersecurity hack") == "cyber"

    def test_keyword_matching_econ(self):
        assert _normalize_tag("fed inflation gdp") == "econ"
        assert _normalize_tag("market trade tariff") == "econ"

    def test_keyword_matching_science(self):
        assert _normalize_tag("climate research study") == "science"

    def test_keyword_matching_local(self):
        assert _normalize_tag("utah cache valley") == "local"
        assert _normalize_tag("logan community county") == "local"

    def test_keyword_matching_domestic(self):
        assert _normalize_tag("trump congress senate") == "domestic"
        assert _normalize_tag("white house election") == "domestic"

    def test_unknown_tag_defaults_to_domestic(self):
        assert _normalize_tag("celebrity gossip") == "domestic"
        assert _normalize_tag("sports") == "domestic"
        assert _normalize_tag("") == "domestic"

    def test_whitespace_stripped(self):
        assert _normalize_tag("  war  ") == "war"


class TestBuildInput:
    def test_basic_domain_analysis(self):
        domain_analysis = {
            "geopolitics": {
                "items": [
                    {
                        "headline": "Test headline",
                        "facts": "Test facts",
                        "analysis": "Test analysis",
                        "links": [{"url": "https://example.com", "label": "Example"}],
                    }
                ]
            }
        }
        result = _build_input(domain_analysis, {}, {"rss": []})
        assert "=== DOMAIN ANALYSES ===" in result
        assert "GEOPOLITICS (1 items)" in result
        assert "Test headline" in result

    def test_seam_data_included(self):
        seam_data = {
            "contested_narratives": [{"topic": "Test", "description": "Desc"}],
            "coverage_gaps": [],
            "key_assumptions": [],
        }
        result = _build_input({}, seam_data, {"rss": []})
        assert "=== SEAM DETECTION RESULTS ===" in result
        assert "contested_narratives" in result

    def test_raw_source_urls_included(self):
        raw_sources = {
            "rss": [
                {"url": "https://example.com/1", "source": "Example 1"},
                {"url": "https://example.com/2", "source": "Example 2"},
            ]
        }
        result = _build_input({}, {}, raw_sources)
        assert "=== SOURCE URL REFERENCE ===" in result
        assert "https://example.com/1" in result

    def test_previous_cross_domain_continuity(self):
        previous = {
            "at_a_glance": [{"headline": "Yesterday's story"}],
            "deep_dives": [{"headline": "Yesterday's dive"}],
        }
        result = _build_input({}, {}, {"rss": []}, previous_cross_domain=previous)
        assert "=== CONTINUITY" in result
        assert "Yesterday's story" in result
        assert "Yesterday's dive" in result

    def test_no_previous_cross_domain(self):
        result = _build_input({}, {}, {"rss": []}, previous_cross_domain=None)
        assert "CONTINUITY" not in result

    def test_worth_reading_always_requested(self):
        result = _build_input({}, {}, {"rss": []})
        assert "=== WORTH READING ===" in result
        assert "worth_reading" in result

    def test_empty_domain_analysis(self):
        result = _build_input({}, {}, {"rss": []})
        assert "GEOPOLITICS" not in result
        assert "(0 items)" not in result

    def test_multiple_domains(self):
        domain_analysis = {
            "geopolitics": {"items": [{"headline": "G1"}]},
            "defense_space": {"items": [{"headline": "D1"}]},
            "ai_tech": {"items": [{"headline": "A1"}]},
            "econ": {"items": [{"headline": "E1"}]},
        }
        result = _build_input(domain_analysis, {}, {"rss": []})
        assert "GEOPOLITICS (1 items)" in result
        assert "DEFENSE_SPACE (1 items)" in result
        assert "AI_TECH (1 items)" in result
        assert "ECON (1 items)" in result


class TestEmptyOutput:
    def test_empty_domain_analysis(self):
        result = _empty_output({})
        assert result["at_a_glance"] == []
        assert result["deep_dives"] == []
        assert result["cross_domain_connections"] == []
        assert result["market_context"] == ""

    def test_domain_with_items(self):
        domain_analysis = {
            "geopolitics": {
                "items": [
                    {
                        "headline": "Test",
                        "facts": "Facts",
                        "analysis": "Analysis",
                        "links": [],
                    }
                ]
            }
        }
        result = _empty_output(domain_analysis)
        assert len(result["at_a_glance"]) == 1
        assert result["at_a_glance"][0]["headline"] == "Test"

    def test_deep_dive_candidate_conversion(self):
        domain_analysis = {
            "geopolitics": {
                "items": [
                    {
                        "headline": "Dive candidate",
                        "facts": "Facts",
                        "analysis": "Analysis",
                        "deep_dive_candidate": True,
                        "deep_dive_rationale": "Important because...",
                        "links": [{"url": "https://example.com"}],
                    }
                ]
            }
        }
        result = _empty_output(domain_analysis)
        assert len(result["deep_dives"]) == 1
        dive = result["deep_dives"][0]
        assert dive["headline"] == "Dive candidate"
        assert "Facts" in dive["body"]
        assert "Analysis" in dive["body"]
        assert "Important because..." in dive["body"]

    def test_market_context_from_econ(self):
        domain_analysis = {
            "econ": {
                "items": [],
                "market_context": "Markets are volatile today.",
            }
        }
        result = _empty_output(domain_analysis)
        assert result["market_context"] == "Markets are volatile today."

    def test_non_dict_domain_result_skipped(self):
        domain_analysis = {"geopolitics": "not a dict"}
        result = _empty_output(domain_analysis)
        assert result["at_a_glance"] == []


class TestCrossDomainRun:
    @patch("stages.cross_domain.call_llm")
    def test_successful_run(self, mock_llm):
        mock_llm.side_effect = [
            {
                "schema_version": 1,
                "cross_domain_connections": [],
                "deep_dives": [{"topic": "Test topic", "angle": "Angle", "why_selected": "Why"}],
                "worth_reading": [{"topic": "Long read", "why_worth_reading": "Because"}],
                "rejected_alternatives": [{"topic": "Other", "reason": "Lower priority"}],
            },
            {
                "at_a_glance": [
                    {
                        "tag": "war",
                        "headline": "Test",
                        "facts": "Facts",
                        "analysis": "Analysis",
                        "source_depth": "widely-reported",
                        "links": [],
                    }
                ],
                "deep_dives": [],
                "cross_domain_connections": [],
                "worth_reading": [],
                "market_context": "Test context",
            },
        ]
        context = {
            "domain_analysis": {
                "geopolitics": {
                    "items": [
                        {
                            "headline": "Test",
                            "facts": "Facts",
                            "analysis": "Analysis",
                            "links": [],
                        }
                    ]
                }
            },
            "seam_data": {},
            "raw_sources": {"rss": []},
        }
        config = {"llm": {"provider": "fireworks"}}
        result = run(context, config)
        assert "cross_domain_plan" in result
        assert "cross_domain_output" in result
        output = result["cross_domain_output"]
        assert len(output["at_a_glance"]) == 1
        assert output["at_a_glance"][0]["tag"] == "war"
        assert mock_llm.call_count == 2

    @patch("stages.cross_domain.call_llm")
    def test_llm_failure_returns_empty(self, mock_llm):
        mock_llm.side_effect = Exception("API error")
        context = {
            "domain_analysis": {},
            "seam_data": {},
            "raw_sources": {"rss": []},
        }
        config = {"llm": {"provider": "fireworks"}}
        result = run(context, config)
        assert "cross_domain_output" in result
        output = result["cross_domain_output"]
        assert output["at_a_glance"] == []
        assert output["deep_dives"] == []

    def test_no_domain_analysis_returns_empty(self):
        context = {
            "domain_analysis": {},
            "seam_data": {},
            "raw_sources": {"rss": []},
        }
        config = {"llm": {"provider": "fireworks"}}
        result = run(context, config)
        assert "cross_domain_output" in result
        output = result["cross_domain_output"]
        assert output["at_a_glance"] == []

    @patch("stages.cross_domain.call_llm")
    def test_at_a_glance_cap_enforced(self, mock_llm):
        items = []
        for i in range(10):
            items.append(
                {
                    "tag": "war",
                    "headline": f"Test {i}",
                    "facts": f"Facts {i}",
                    "analysis": f"Analysis {i}",
                    "source_depth": "single-source",
                    "links": [],
                }
            )
        mock_llm.side_effect = [
            {
                "schema_version": 1,
                "cross_domain_connections": [],
                "deep_dives": [{"topic": "Test topic", "angle": "Angle", "why_selected": "Why"}],
                "worth_reading": [{"topic": "Long read", "why_worth_reading": "Because"}],
                "rejected_alternatives": [{"topic": "Other", "reason": "Lower priority"}],
            },
            {
                "at_a_glance": items,
                "deep_dives": [],
                "cross_domain_connections": [],
                "worth_reading": [],
            },
        ]
        context = {
            "domain_analysis": {"geopolitics": {"items": [{"headline": "Test"}]}},
            "seam_data": {},
            "raw_sources": {"rss": []},
        }
        config = {
            "llm": {"provider": "fireworks"},
            "digest": {"at_a_glance": {"max_items": 7}},
        }
        result = run(context, config)
        assert len(result["cross_domain_output"]["at_a_glance"]) == 7

    @patch("stages.cross_domain.call_llm")
    def test_url_validation_filters_unknown_domains(self, mock_llm):
        mock_llm.side_effect = [
            {
                "schema_version": 1,
                "cross_domain_connections": [],
                "deep_dives": [{"topic": "Test topic", "angle": "Angle", "why_selected": "Why"}],
                "worth_reading": [{"topic": "Long read", "why_worth_reading": "Because"}],
                "rejected_alternatives": [{"topic": "Other", "reason": "Lower priority"}],
            },
            {
                "at_a_glance": [
                    {
                        "tag": "war",
                        "headline": "Test",
                        "facts": "Facts",
                        "analysis": "Analysis",
                        "source_depth": "widely-reported",
                        "links": [
                            {"url": "https://example.com/valid", "label": "Valid"},
                            {"url": "https://unknown.com/fake", "label": "Fake"},
                        ],
                    }
                ],
                "deep_dives": [],
                "cross_domain_connections": [],
                "worth_reading": [],
            },
        ]
        context = {
            "domain_analysis": {"geopolitics": {"items": [{"headline": "Test"}]}},
            "seam_data": {},
            "raw_sources": {
                "rss": [{"url": "https://example.com/valid", "source": "Example"}]
            },
        }
        config = {"llm": {"provider": "fireworks"}}
        result = run(context, config)
        links = result["cross_domain_output"]["at_a_glance"][0]["links"]
        assert len(links) == 1
        assert links[0]["url"] == "https://example.com/valid"

    @patch("stages.cross_domain.call_llm")
    def test_url_validation_rejects_known_domain_unknown_path(self, mock_llm):
        mock_llm.side_effect = [
            {
                "schema_version": 1,
                "cross_domain_connections": [],
                "deep_dives": [],
                "worth_reading": [],
                "rejected_alternatives": [],
            },
            {
                "at_a_glance": [
                    {
                        "tag": "war",
                        "headline": "Test",
                        "facts": "Facts",
                        "analysis": "Analysis",
                        "source_depth": "widely-reported",
                        "links": [
                            {"url": "https://example.com/other", "label": "Other"},
                        ],
                    }
                ],
                "deep_dives": [],
                "cross_domain_connections": [],
                "worth_reading": [],
            },
        ]
        context = {
            "domain_analysis": {"geopolitics": {"items": [{"headline": "Test"}]}},
            "seam_data": {},
            "raw_sources": {
                "rss": [{"url": "https://example.com/valid", "source": "Example"}]
            },
        }
        config = {"llm": {"provider": "fireworks"}}
        result = run(context, config)
        links = result["cross_domain_output"]["at_a_glance"][0]["links"]
        assert links == []

    @patch("stages.cross_domain.call_llm")
    def test_final_validation_keeps_domain_analysis_link(self, mock_llm):
        mock_llm.side_effect = [
            {
                "schema_version": 1,
                "cross_domain_connections": [],
                "deep_dives": [],
                "worth_reading": [],
                "rejected_alternatives": [],
            },
            {
                "at_a_glance": [
                    {
                        "tag": "ai",
                        "headline": "Test",
                        "facts": "Facts",
                        "analysis": "Analysis",
                        "source_depth": "single-source",
                        "links": [
                            {"url": "https://analysis.example/story", "label": "A"},
                        ],
                    }
                ],
                "deep_dives": [],
                "cross_domain_connections": [],
                "worth_reading": [],
            },
        ]
        context = {
            "domain_analysis": {
                "ai_tech": {
                    "items": [
                        {
                            "headline": "Test",
                            "links": [{"url": "https://analysis.example/story"}],
                        }
                    ]
                }
            },
            "seam_data": {},
            "raw_sources": {"rss": []},
        }
        config = {"llm": {"provider": "fireworks"}}
        result = run(context, config)
        links = result["cross_domain_output"]["at_a_glance"][0]["links"]
        assert links == [{"url": "https://analysis.example/story", "label": "A"}]

    @patch("stages.cross_domain.call_llm")
    def test_worth_reading_url_validation(self, mock_llm):
        mock_llm.side_effect = [
            {
                "schema_version": 1,
                "cross_domain_connections": [],
                "deep_dives": [{"topic": "Test topic", "angle": "Angle", "why_selected": "Why"}],
                "worth_reading": [{"topic": "Long read", "why_worth_reading": "Because"}],
                "rejected_alternatives": [{"topic": "Other", "reason": "Lower priority"}],
            },
            {
                "at_a_glance": [],
                "deep_dives": [],
                "cross_domain_connections": [],
                "worth_reading": [
                    {
                        "title": "Test",
                        "url": "https://unknown.com/fake",
                        "source": "Unknown",
                        "description": "Desc",
                        "read_time": "10 min",
                    }
                ],
            },
        ]
        context = {
            "domain_analysis": {"geopolitics": {"items": [{"headline": "Test"}]}},
            "seam_data": {},
            "raw_sources": {"rss": []},
        }
        config = {"llm": {"provider": "fireworks"}}
        result = run(context, config)
        worth = result["cross_domain_output"]["worth_reading"]
        assert worth[0]["url"] == ""

    def test_tag_normalisation_in_run(self):
        """Test that unknown tags get normalized to domestic."""
        with patch("stages.cross_domain.call_llm") as mock_llm:
            mock_llm.side_effect = [
                {
                    "schema_version": 1,
                    "cross_domain_connections": [],
                    "deep_dives": [{"topic": "Test topic", "angle": "Angle", "why_selected": "Why"}],
                    "worth_reading": [{"topic": "Long read", "why_worth_reading": "Because"}],
                    "rejected_alternatives": [{"topic": "Other", "reason": "Lower priority"}],
                },
                {
                    "at_a_glance": [
                        {
                            "tag": "unknown_tag",
                            "headline": "Test",
                            "facts": "Facts",
                            "analysis": "Analysis",
                            "source_depth": "single-source",
                            "links": [],
                        }
                    ],
                    "deep_dives": [],
                    "cross_domain_connections": [],
                    "worth_reading": [],
                },
            ]
            context = {
                "domain_analysis": {"geopolitics": {"items": [{"headline": "Test"}]}},
                "seam_data": {},
                "raw_sources": {"rss": []},
            }
            config = {"llm": {"provider": "fireworks"}}
            result = run(context, config)
            assert result["cross_domain_output"]["at_a_glance"][0]["tag"] == "domestic"

    def test_market_context_fallback_from_econ(self):
        """Test that market_context falls back to econ domain analysis."""
        with patch("stages.cross_domain.call_llm") as mock_llm:
            mock_llm.side_effect = [
                {
                    "schema_version": 1,
                    "cross_domain_connections": [],
                    "deep_dives": [{"topic": "Test topic", "angle": "Angle", "why_selected": "Why"}],
                    "worth_reading": [{"topic": "Long read", "why_worth_reading": "Because"}],
                    "rejected_alternatives": [{"topic": "Other", "reason": "Lower priority"}],
                },
                {
                    "at_a_glance": [],
                    "deep_dives": [],
                    "cross_domain_connections": [],
                    "worth_reading": [],
                },
            ]
            context = {
                "domain_analysis": {
                    "geopolitics": {"items": [{"headline": "Test"}]},
                    "econ": {
                        "items": [],
                        "market_context": "Fallback context",
                    },
                },
                "seam_data": {},
                "raw_sources": {"rss": []},
            }
            config = {"llm": {"provider": "fireworks"}}
            result = run(context, config)
            assert result["cross_domain_output"]["market_context"] == "Fallback context"
