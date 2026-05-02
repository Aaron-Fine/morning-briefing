"""Tests for stages/assemble.py — template assembly and rendering."""

import sys
import os
from datetime import datetime
from unittest.mock import patch, MagicMock
from markupsafe import Markup
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.assemble import (
    _item_to_glance,
    _domain_item_to_deep_dive,
    _build_from_domain_analysis,
    _extract_peripheral_data,
    _visible_stage_failures,
    _select_inline_seam_annotations,
    _TAG_LABELS,
    run,
)


class TestItemToGlance:
    def test_basic_item(self):
        item = {
            "tag": "ai",
            "headline": "AI breakthrough announced",
            "facts": "Some facts here.",
            "analysis": "Some analysis here.",
            "links": [{"url": "https://example.com", "label": "Example"}],
            "source_depth": "widely-reported",
        }
        result = _item_to_glance(item)
        assert result["tag"] == "ai"
        assert result["tag_label"] == "AI"
        assert result["headline"] == "AI breakthrough announced"
        assert result["facts"] == "Some facts here."
        assert result["analysis"] == "Some analysis here."
        assert result["cross_domain_note"] == ""
        assert result["links"] == [{"url": "https://example.com", "label": "Example"}]
        assert result["source_depth"] == "widely-reported"
        assert result["connection_hooks"] == []

    def test_context_joins_facts_and_analysis(self):
        item = {"facts": "Fact one.", "analysis": "Analysis one."}
        result = _item_to_glance(item)
        assert result["context"] == "Fact one. Analysis one."

    def test_context_includes_cross_domain_note(self):
        item = {
            "facts": "Fact one.",
            "analysis": "Analysis one.",
            "cross_domain_note": "Connects to AI policy.",
        }
        result = _item_to_glance(item)
        assert result["context"] == "Fact one. Analysis one. (Connects to AI policy.)"

    def test_context_empty_when_no_fields(self):
        item = {"facts": "", "analysis": "", "cross_domain_note": ""}
        result = _item_to_glance(item)
        assert result["context"] == ""

    def test_tag_label_fallback_to_capitalized_tag(self):
        item = {"tag": "unknown_tag"}
        result = _item_to_glance(item)
        assert result["tag_label"] == "Unknown_tag"

    def test_tag_label_uses_tag_labels_mapping(self):
        for tag, expected_label in _TAG_LABELS.items():
            item = {"tag": tag}
            result = _item_to_glance(item)
            assert result["tag_label"] == expected_label

    def test_explicit_tag_label_overrides_mapping(self):
        item = {"tag": "ai", "tag_label": "Custom AI Label"}
        result = _item_to_glance(item)
        assert result["tag_label"] == "Custom AI Label"

    def test_connection_hooks_preserved(self):
        hooks = [{"entity": "OpenAI", "region": "US", "theme": "AI", "policy": ""}]
        item = {"connection_hooks": hooks}
        result = _item_to_glance(item)
        assert result["connection_hooks"] == hooks


class TestInlineSeamAnnotations:
    def test_attaches_annotation_by_item_id(self):
        items = [{"item_id": "item-1", "headline": "Story"}]
        annotations = {
            "per_item": [
                {
                    "item_id": "item-1",
                    "one_line": "The non-Western read: this is escalation.",
                    "confidence": "high",
                    "seam_type": "framing_divergence",
                }
            ]
        }

        result = _select_inline_seam_annotations(items, annotations)

        assert result[0]["seam_annotation"]["one_line"].startswith(
            "The non-Western read:"
        )

    def test_keeps_highest_confidence_annotation(self):
        items = [{"item_id": "item-1", "headline": "Story"}]
        annotations = {
            "per_item": [
                {"item_id": "item-1", "one_line": "Low.", "confidence": "low"},
                {"item_id": "item-1", "one_line": "High.", "confidence": "high"},
            ]
        }

        result = _select_inline_seam_annotations(items, annotations)

        assert result[0]["seam_annotation"]["one_line"] == "High."


class TestDomainItemToDeepDive:
    def test_basic_conversion(self):
        item = {
            "headline": "Deep dive headline",
            "tag": "war",
            "facts": "<p>Facts paragraph.</p>",
            "analysis": "<p>Analysis paragraph.</p>",
            "deep_dive_rationale": "Why this matters.",
            "links": [{"url": "https://example.com", "label": "Example"}],
            "source_depth": "corroborated",
        }
        result = _domain_item_to_deep_dive(item)
        assert result["headline"] == "Deep dive headline"
        assert result["tag"] == "war"
        assert result["why_it_matters"] == "Why this matters."
        assert result["further_reading"] == [
            {"url": "https://example.com", "label": "Example"}
        ]
        assert result["source_depth"] == "corroborated"
        assert "<p>Facts paragraph.</p>" in result["body"]
        assert "<p>Analysis paragraph.</p>" in result["body"]

    def test_body_joins_facts_and_analysis(self):
        item = {"facts": "F1", "analysis": "A1"}
        result = _domain_item_to_deep_dive(item)
        assert result["body"] == "<p>F1</p>\n<p>A1</p>"

    def test_body_only_facts(self):
        item = {"facts": "F1", "analysis": ""}
        result = _domain_item_to_deep_dive(item)
        assert result["body"] == "<p>F1</p>"

    def test_body_only_analysis(self):
        item = {"facts": "", "analysis": "A1"}
        result = _domain_item_to_deep_dive(item)
        assert result["body"] == "<p>A1</p>"

    def test_empty_body(self):
        item = {"facts": "", "analysis": ""}
        result = _domain_item_to_deep_dive(item)
        assert result["body"] == ""

    def test_missing_fields_defaults(self):
        item = {}
        result = _domain_item_to_deep_dive(item)
        assert result["headline"] == ""
        assert result["tag"] == ""
        assert result["body"] == ""
        assert result["why_it_matters"] == ""
        assert result["further_reading"] == []
        assert result["source_depth"] == ""


class TestBuildFromDomainAnalysis:
    def test_basic_extraction(self):
        context = {
            "domain_analysis": {
                "ai_tech": {
                    "items": [
                        {
                            "tag": "ai",
                            "headline": "AI story",
                            "facts": "Facts",
                            "analysis": "Analysis",
                        },
                        {
                            "tag": "tech",
                            "headline": "Tech story",
                            "facts": "Tech facts",
                            "analysis": "Tech analysis",
                        },
                    ]
                },
                "geopolitics": {
                    "items": [
                        {
                            "tag": "war",
                            "headline": "War story",
                            "facts": "War facts",
                            "analysis": "War analysis",
                        }
                    ]
                },
            }
        }
        config = {
            "digest": {
                "at_a_glance": {"max_items": 14, "normal_items": 10},
                "deep_dives": {"count": 2},
            }
        }
        at_a_glance, deep_dives, market_context = _build_from_domain_analysis(
            context, config
        )
        assert len(at_a_glance) == 3
        assert len(deep_dives) == 0
        assert market_context == ""

    def test_market_context_from_econ(self):
        context = {
            "domain_analysis": {
                "econ": {
                    "market_context": "Markets are up today.",
                    "items": [],
                }
            }
        }
        config = {
            "digest": {
                "at_a_glance": {"max_items": 14, "normal_items": 10},
                "deep_dives": {"count": 2},
            }
        }
        _, _, market_context = _build_from_domain_analysis(context, config)
        assert market_context == "Markets are up today."

    def test_deep_dive_candidates_extracted(self):
        context = {
            "domain_analysis": {
                "ai_tech": {
                    "items": [
                        {
                            "tag": "ai",
                            "headline": "AI deep dive",
                            "facts": "Facts",
                            "analysis": "Analysis",
                            "deep_dive_candidate": True,
                            "deep_dive_rationale": "Important AI topic.",
                        },
                        {
                            "tag": "tech",
                            "headline": "Regular tech story",
                            "facts": "Tech facts",
                            "analysis": "Tech analysis",
                        },
                    ]
                }
            }
        }
        config = {
            "digest": {
                "at_a_glance": {"max_items": 14, "normal_items": 10},
                "deep_dives": {"count": 2},
            }
        }
        at_a_glance, deep_dives, _ = _build_from_domain_analysis(context, config)
        assert len(at_a_glance) == 1
        assert len(deep_dives) == 1
        assert deep_dives[0]["headline"] == "AI deep dive"

    def test_deep_dive_count_capped(self):
        candidates = [
            {
                "tag": "ai",
                "headline": f"Deep dive {i}",
                "facts": f"Facts {i}",
                "analysis": f"Analysis {i}",
                "deep_dive_candidate": True,
            }
            for i in range(5)
        ]
        context = {"domain_analysis": {"ai_tech": {"items": candidates}}}
        config = {
            "digest": {
                "at_a_glance": {"max_items": 14, "normal_items": 10},
                "deep_dives": {"count": 2},
            }
        }
        _, deep_dives, _ = _build_from_domain_analysis(context, config)
        assert len(deep_dives) == 2

    def test_sorting_by_source_depth(self):
        items = [
            {
                "tag": "ai",
                "headline": "Single",
                "facts": "F",
                "source_depth": "single-source",
            },
            {
                "tag": "war",
                "headline": "Widely",
                "facts": "F",
                "source_depth": "widely-reported",
            },
            {
                "tag": "tech",
                "headline": "Corroborated",
                "facts": "F",
                "source_depth": "corroborated",
            },
        ]
        context = {"domain_analysis": {"misc": {"items": items}}}
        config = {
            "digest": {
                "at_a_glance": {"max_items": 14, "normal_items": 10},
                "deep_dives": {"count": 2},
            }
        }
        at_a_glance, _, _ = _build_from_domain_analysis(context, config)
        headlines = [i["headline"] for i in at_a_glance]
        assert headlines == ["Widely", "Corroborated", "Single"]

    def test_at_a_glance_cap_enforced(self):
        items = [
            {"tag": "ai", "headline": f"Item {i}", "facts": "F"} for i in range(20)
        ]
        context = {"domain_analysis": {"misc": {"items": items}}}
        config = {
            "digest": {
                "at_a_glance": {"max_items": 7, "normal_items": 10},
                "deep_dives": {"count": 2},
            }
        }
        at_a_glance, _, _ = _build_from_domain_analysis(context, config)
        assert len(at_a_glance) == 7

    def test_empty_domain_analysis(self):
        context = {"domain_analysis": {}}
        config = {
            "digest": {
                "at_a_glance": {"max_items": 14, "normal_items": 10},
                "deep_dives": {"count": 2},
            }
        }
        at_a_glance, deep_dives, market_context = _build_from_domain_analysis(
            context, config
        )
        assert at_a_glance == []
        assert deep_dives == []
        assert market_context == ""


class TestExtractPeripheralData:
    def test_uses_context_values_when_present(self):
        context = {
            "spiritual": {"date_range": "Jan 1-7", "reading": "Test"},
            "weather": {"current_temp_f": 72},
            "weather_html": "<svg>weather</svg>",
            "calendar": {"events": [{"date": "Monday", "event": "Meeting"}]},
            "local_items": [{"headline": "Local story"}],
        }
        raw_sources = {}
        result = _extract_peripheral_data(context, raw_sources)
        assert result["spiritual"] == {"date_range": "Jan 1-7", "reading": "Test"}
        assert result["weather"] == {"current_temp_f": 72}
        assert result["weather_html"] == "<svg>weather</svg>"
        assert result["week_ahead"] == [{"date": "Monday", "event": "Meeting"}]
        assert result["local_items"] == [{"headline": "Local story"}]

    def test_spiritual_fallback_to_raw_sources(self):
        context = {}
        raw_sources = {
            "come_follow_me": {
                "date_range": "Jan 1-7",
                "reading": "Test",
                "scripture_text": "Scripture text",
            }
        }
        result = _extract_peripheral_data(context, raw_sources)
        assert result["spiritual"]["date_range"] == "Jan 1-7"
        assert result["spiritual"]["reflection"] == "Scripture text"

    def test_weather_fallback_to_raw_sources(self):
        context = {}
        raw_sources = {"weather": {"current_temp_f": 65}}
        result = _extract_peripheral_data(context, raw_sources)
        assert result["weather"] == {"current_temp_f": 65}

    def test_local_items_fallback_to_raw_sources(self):
        context = {}
        raw_sources = {"local_news": [{"headline": "Fallback local"}]}
        result = _extract_peripheral_data(context, raw_sources)
        assert result["local_items"] == [{"headline": "Fallback local"}]

    def test_missing_spiritual_returns_none(self):
        context = {}
        raw_sources = {}
        result = _extract_peripheral_data(context, raw_sources)
        assert result["spiritual"] is None

    def test_empty_calendar_events(self):
        context = {"calendar": {}}
        raw_sources = {}
        result = _extract_peripheral_data(context, raw_sources)
        assert result["week_ahead"] == []


class TestVisibleStageFailures:
    def test_artifacts_only_hides_failures(self):
        context = {"run_meta": {"stage_failures": [{"stage": "weather"}]}}
        assert _visible_stage_failures(
            context,
            {"digest": {"failure_visibility": "artifacts_only"}},
            dry_run=True,
        ) == []

    def test_dry_run_mode_shows_failures_only_in_dry_run(self):
        context = {"run_meta": {"stage_failures": [{"stage": "weather"}]}}
        config = {"digest": {"failure_visibility": "dry_run"}}
        assert _visible_stage_failures(context, config, dry_run=True) == [
            {"stage": "weather"}
        ]
        assert _visible_stage_failures(context, config, dry_run=False) == []

    def test_always_mode_shows_failures(self):
        context = {"run_meta": {"stage_failures": [{"stage": "weather"}]}}
        assert _visible_stage_failures(
            context,
            {"digest": {"failure_visibility": "always"}},
            dry_run=False,
        ) == [{"stage": "weather"}]


class TestAssembleRun:
    @patch("stages.assemble.render_email")
    def test_phase_3_cross_domain_output(self, mock_render):
        mock_render.return_value = "<html>rendered</html>"
        context = {
            "cross_domain_output": {
                "at_a_glance": [
                    {
                        "tag": "ai",
                        "headline": "AI story",
                        "facts": "Facts",
                        "analysis": "Analysis",
                    }
                ],
                "deep_dives": [
                    {
                        "headline": "Deep dive",
                        "body": "<p>Body</p>",
                        "why_it_matters": "Why",
                    }
                ],
                "market_context": "Markets up.",
                "worth_reading": [
                    {
                        "url": "https://example.com",
                        "title": "Article",
                        "source": "Ex",
                        "read_time": "5 min",
                        "description": "Desc",
                    }
                ],
                "cross_domain_connections": [{"entity": "OpenAI"}],
            },
            "seam_data": {
                "contested_narratives": [],
                "coverage_gaps": [],
                "key_assumptions": [],
            },
            "raw_sources": {},
        }
        config = {
            "digest": {
                "at_a_glance": {"max_items": 14, "normal_items": 10},
                "deep_dives": {"count": 2},
            }
        }

        result = run(context, config)

        assert "html" in result
        assert "template_data" in result
        assert "digest_json" in result
        assert len(result["template_data"]["at_a_glance"]) == 1
        assert len(result["template_data"]["deep_dives"]) == 1
        assert result["template_data"]["market_context"] == "Markets up."
        assert len(result["template_data"]["worth_reading"]) == 1
        assert result["digest_json"]["cross_domain_connections"] == [
            {
                "entity": "OpenAI",
                "title": "",
                "summary": "",
                "domains": [],
                "entities": [],
                "why_it_matters": "",
            }
        ]
        mock_render.assert_called_once()

    @patch("stages.assemble.render_email")
    def test_phase_1_domain_analysis(self, mock_render):
        mock_render.return_value = "<html>phase1</html>"
        context = {
            "domain_analysis": {
                "ai_tech": {
                    "items": [
                        {
                            "tag": "ai",
                            "headline": "AI story",
                            "facts": "Facts",
                            "analysis": "Analysis",
                        }
                    ]
                },
                "econ": {
                    "market_context": "Econ context.",
                    "items": [],
                },
            },
            "seam_data": {
                "contested_narratives": [],
                "coverage_gaps": [],
                "key_assumptions": [],
            },
            "raw_sources": {},
        }
        config = {
            "digest": {
                "at_a_glance": {"max_items": 14, "normal_items": 10},
                "deep_dives": {"count": 2},
            },
            "rss": {"feeds": [{"name": "TechCrunch"}]},
            "local_news": {"sources": [{"name": "Local Paper"}]},
            "youtube": {"analysis_channels": [{"name": "AI Channel"}]},
        }

        result = run(context, config)

        assert "html" in result
        assert len(result["template_data"]["at_a_glance"]) == 1
        assert result["template_data"]["market_context"] == "Econ context."
        assert result["template_data"]["worth_reading"] == []
        assert result["template_data"]["rss_source_names"] == "TechCrunch, Local Paper"
        assert result["template_data"]["yt_source_names"] == "AI Channel"

    @patch("stages.assemble.render_email")
    def test_empty_fallback_produces_valid_output(self, mock_render):
        mock_render.return_value = "<html>empty</html>"
        context = {
            "seam_data": {},
            "raw_sources": {},
        }
        config = {}

        result = run(context, config)

        assert result["template_data"]["at_a_glance"] == []
        assert result["template_data"]["deep_dives"] == []
        assert result["template_data"]["market_context"] == ""
        assert result["template_data"]["worth_reading"] == []

    @patch("stages.assemble.render_email")
    def test_malformed_cross_domain_output_falls_back_to_domain_analysis(
        self, mock_render
    ):
        mock_render.return_value = "<html>fallback</html>"
        context = {
            "cross_domain_output": {"at_a_glance": "bad"},
            "domain_analysis": {
                "ai_tech": {
                    "items": [
                        {
                            "tag": "ai",
                            "headline": "Domain fallback",
                            "facts": "Facts",
                            "analysis": "Analysis",
                            "links": [],
                        }
                    ]
                }
            },
            "seam_data": {},
            "raw_sources": {},
        }
        config = {
            "digest": {
                "at_a_glance": {"max_items": 14, "normal_items": 10},
                "deep_dives": {"count": 2},
            }
        }

        result = run(context, config)

        assert result["template_data"]["at_a_glance"][0]["headline"] == (
            "Domain fallback"
        )
        assert result["assemble_contract_issues"] == [
            {
                "artifact": "cross_domain_output",
                "path": "cross_domain_output.at_a_glance",
                "message": "at_a_glance is not a list",
            }
        ]
        assert result["digest_json"]["assemble_contract_issues"] == (
            result["assemble_contract_issues"]
        )

    @patch("stages.assemble.render_email")
    def test_malformed_seam_annotations_are_reported(self, mock_render):
        mock_render.return_value = "<html>seam fallback</html>"
        context = {
            "cross_domain_output": {
                "at_a_glance": [
                    {
                        "item_id": "item-1",
                        "tag": "ai",
                        "headline": "AI story",
                        "facts": "Facts",
                        "analysis": "Analysis",
                    }
                ],
                "deep_dives": [],
                "market_context": "",
                "worth_reading": [],
                "cross_domain_connections": [],
            },
            "seam_annotations": {"per_item": "bad"},
            "seam_data": {},
            "raw_sources": {},
        }

        result = run(context, {"digest": {}})

        assert "seam_annotation" not in result["template_data"]["at_a_glance"][0]
        assert result["assemble_contract_issues"] == [
            {
                "artifact": "seam_annotations",
                "path": "seam_annotations.per_item",
                "message": "per_item is not a list",
            }
        ]

    @patch("stages.assemble.render_email")
    def test_deep_dive_body_wrapped_in_markup(self, mock_render):
        mock_render.return_value = "<html>with markup</html>"
        context = {
            "cross_domain_output": {
                "at_a_glance": [],
                "deep_dives": [
                    {
                        "headline": "Deep dive",
                        "body": "<p>HTML body</p>",
                        "why_it_matters": "Why",
                    }
                ],
                "market_context": "",
                "worth_reading": [],
                "cross_domain_connections": [],
            },
            "seam_data": {},
            "raw_sources": {},
        }
        config = {
            "digest": {
                "at_a_glance": {"max_items": 14, "normal_items": 10},
                "deep_dives": {"count": 2},
            }
        }

        run(context, config)

        call_args = mock_render.call_args[0][0]
        deep_dives = call_args["deep_dives"]
        assert isinstance(deep_dives[0]["body"], Markup)

    @patch("stages.assemble.render_email")
    def test_weather_html_wrapped_in_markup(self, mock_render):
        mock_render.return_value = "<html>weather</html>"
        context = {
            "cross_domain_output": {
                "at_a_glance": [],
                "deep_dives": [],
                "market_context": "",
                "worth_reading": [],
                "cross_domain_connections": [],
            },
            "weather_html": "<svg>weather svg</svg>",
            "seam_data": {},
            "raw_sources": {},
        }
        config = {
            "digest": {
                "at_a_glance": {"max_items": 14, "normal_items": 10},
                "deep_dives": {"count": 2},
            }
        }

        run(context, config)

        call_args = mock_render.call_args[0][0]
        assert isinstance(call_args["weather_html"], Markup)

    @patch("stages.assemble.render_email")
    @patch("stages.assemble.now_local")
    def test_date_and_time_generated(self, mock_now_local, mock_render):
        mock_render.return_value = "<html>date test</html>"
        mock_now_local.return_value = datetime(
            2026, 4, 17, 6, 5, tzinfo=ZoneInfo("America/Denver")
        )
        context = {
            "cross_domain_output": {
                "at_a_glance": [],
                "deep_dives": [],
                "market_context": "",
                "worth_reading": [],
                "cross_domain_connections": [],
            },
            "seam_data": {},
            "raw_sources": {},
        }
        config = {
            "digest": {
                "at_a_glance": {"max_items": 14, "normal_items": 10},
                "deep_dives": {"count": 2},
            },
        }

        run(context, config)

        call_args = mock_render.call_args[0][0]
        assert call_args["date_display"] == "Friday, April 17, 2026"
        assert call_args["generated_at"] == "6:05 AM MDT"

    @patch("stages.assemble.render_email")
    def test_seam_data_passed_through(self, mock_render):
        mock_render.return_value = "<html>seams</html>"
        context = {
            "cross_domain_output": {
                "at_a_glance": [],
                "deep_dives": [],
                "market_context": "",
                "worth_reading": [],
                "cross_domain_connections": [],
            },
            "seam_data": {
                "contested_narratives": [
                    {
                        "topic": "Topic A",
                        "description": "Desc A",
                        "sources_a": "Src A",
                        "sources_b": "Src B",
                    }
                ],
                "coverage_gaps": [
                    {
                        "topic": "Gap A",
                        "description": "Desc A",
                        "present_in": "X",
                        "absent_from": "Y",
                    }
                ],
                "key_assumptions": [
                    {
                        "topic": "Assumption A",
                        "assumption": "A",
                        "invalidator": "B",
                        "confidence": "High",
                    }
                ],
            },
            "raw_sources": {},
        }
        config = {
            "digest": {
                "at_a_glance": {"max_items": 14, "normal_items": 10},
                "deep_dives": {"count": 2},
            }
        }

        result = run(context, config)

        assert len(result["template_data"]["contested_narratives"]) == 1
        assert len(result["template_data"]["coverage_gaps"]) == 1
        assert len(result["template_data"]["key_assumptions"]) == 1

    @patch("stages.assemble.render_email")
    def test_coverage_gap_diagnostics_only_in_dry_run(self, mock_render):
        mock_render.return_value = "<html>diagnostics</html>"
        context = {
            "cross_domain_output": {
                "at_a_glance": [],
                "deep_dives": [],
                "market_context": "",
                "worth_reading": [],
                "cross_domain_connections": [],
            },
            "coverage_gaps": {
                "schema_version": 1,
                "date": "2026-04-18",
                "gaps": [{"topic": "Gap A", "description": "Desc", "significance": "high"}],
                "recurring_patterns": [],
            },
            "seam_data": {},
            "raw_sources": {},
        }
        config = {
            "digest": {
                "at_a_glance": {"max_items": 14, "normal_items": 10},
                "deep_dives": {"count": 2},
            }
        }

        dry_run_result = run(context, config, dry_run=True)
        normal_result = run(context, config, dry_run=False)

        assert dry_run_result["template_data"]["coverage_gap_diagnostics"]["gaps"][0]["topic"] == "Gap A"
        assert normal_result["template_data"]["coverage_gap_diagnostics"] == {}

    @patch("stages.assemble.render_email")
    def test_stage_failures_passed_to_template_when_configured(self, mock_render):
        mock_render.return_value = "<html>failures</html>"
        context = {
            "cross_domain_output": {
                "at_a_glance": [],
                "deep_dives": [],
                "cross_domain_connections": [],
                "worth_reading": [],
            },
            "raw_sources": {},
            "run_meta": {
                "stage_failures": [
                    {"stage": "prepare_weather", "error": "timeout"}
                ]
            },
        }
        config = {"digest": {"failure_visibility": "dry_run"}}

        result = run(context, config, dry_run=True)

        assert result["template_data"]["stage_failures"] == [
            {"stage": "prepare_weather", "error": "timeout"}
        ]


class TestSourceCaps:
    def test_enforces_at_a_glance_per_outlet_cap(self):
        from stages.assemble import _enforce_source_caps

        items = [
            {"links": [{"url": "https://example.com/1"}]},
            {"links": [{"url": "https://example.com/2"}]},
            {"links": [{"url": "https://example.com/3"}]},
            {"links": [{"url": "https://other.com/1"}]},
        ]
        result = _enforce_source_caps(items, max_per_outlet=2, section_name="test")
        assert len(result) == 3
        assert result[0]["links"][0]["url"] == "https://example.com/1"
        assert result[1]["links"][0]["url"] == "https://example.com/2"
        assert result[2]["links"][0]["url"] == "https://other.com/1"

    def test_enforces_deep_dive_per_outlet_cap(self):
        from stages.assemble import _enforce_source_caps

        items = [
            {"further_reading": [{"url": "https://example.com/1"}]},
            {"further_reading": [{"url": "https://example.com/2"}]},
        ]
        result = _enforce_source_caps(items, max_per_outlet=1, section_name="test")
        assert len(result) == 1

    def test_records_source_cap_diagnostics(self):
        from stages.assemble import _enforce_source_caps

        diagnostics = []
        items = [
            {"headline": "Keep", "links": [{"url": "https://example.com/1"}]},
            {"headline": "Drop", "links": [{"url": "https://example.com/2"}]},
        ]
        result = _enforce_source_caps(
            items,
            max_per_outlet=1,
            section_name="test",
            diagnostics=diagnostics,
        )
        assert len(result) == 1
        assert diagnostics == [
            {
                "kind": "source_cap_enforced",
                "section": "test",
                "outlet": "example.com",
                "max_per_outlet": 1,
                "headline": "Drop",
                "reason": "per_outlet_cap_exceeded",
            }
        ]
