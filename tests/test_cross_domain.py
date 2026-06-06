"""Tests for stages/cross_domain.py."""

import sys
import os
import copy
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.conftest import llm_result
from morning_digest.llm import LLMUsage

from cross_domain.parse import (
    _validated_output as _vo,
    _REASON_PHRASE_OVERLAP,
    _fallback_outputs,
)

from stages.cross_domain import (
    _build_input,
    _cap_at_a_glance_items,
    _empty_output,
    _TAG_LABELS,
    run,
)


class TestAtAGlanceCap:
    def _item(
        self,
        headline: str,
        tag: str,
        source: str,
        source_depth: str = "single-source",
        cross_domain_note: str | None = "note",
    ) -> dict:
        return {
            "headline": headline,
            "tag": tag,
            "source_depth": source_depth,
            "cross_domain_note": cross_domain_note,
            "links": [{"label": source, "url": f"https://example.com/{headline}"}],
        }

    def test_cap_preserves_available_primary_tags(self):
        items = [
            self._item("war 1", "war", "A", "widely-reported"),
            self._item("war 2", "war", "A", "widely-reported"),
            self._item("war 3", "war", "B", "widely-reported"),
            self._item("defense 1", "defense", "C", "single-source"),
            self._item("ai 1", "ai", "D", "single-source"),
            self._item("energy 1", "energy", "E", "single-source"),
        ]

        capped = _cap_at_a_glance_items(items, 4)

        assert len(capped) == 4
        assert {"war", "ai", "defense"} <= {item["tag"] for item in capped}

    def test_cap_avoids_source_concentration_when_alternatives_exist(self):
        items = [
            self._item("war 1", "war", "A", "widely-reported"),
            self._item("war 2", "war", "A", "widely-reported"),
            self._item("war 3", "war", "A", "widely-reported"),
            self._item("ai 1", "ai", "B", "single-source"),
            self._item("defense 1", "defense", "C", "single-source"),
            self._item("econ 1", "econ", "D", "single-source"),
            self._item("energy 1", "energy", "E", "single-source"),
        ]

        capped = _cap_at_a_glance_items(items, 5)
        source_a_count = sum(
            1 for item in capped if item["links"][0]["label"] == "A"
        )

        assert len(capped) == 5
        assert source_a_count <= 2


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
            llm_result({
                "schema_version": 1,
                "cross_domain_connections": [],
                "deep_dives": [{"topic": "Test topic", "angle": "Angle", "why_selected": "Why"}],
                "worth_reading": [{"topic": "Long read", "why_worth_reading": "Because"}],
                "rejected_alternatives": [{"topic": "Other", "reason": "Lower priority"}],
            }),
            llm_result({
                "at_a_glance": [
                    {"item_id": "geo-1", "cross_domain_note": None}
                ],
                "deep_dives": [],
                "cross_domain_connections": [],
                "worth_reading": [],
                "market_context": "Test context",
            }),
        ]
        context = {
            "domain_analysis": {
                "geopolitics": {
                    "items": [
                        {
                            "item_id": "geo-1",
                            "tag": "war",
                            "headline": "Test",
                            "facts": "Facts",
                            "analysis": "Analysis",
                            "source_depth": "widely-reported",
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
            "domain_analysis": {
                "geopolitics": {
                    "items": [
                        {
                            "headline": "Fallback",
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
        assert "validation_diagnostics" in result
        assert result["cross_domain_plan"]["schema_version"] == 1
        output = result["cross_domain_output"]
        assert output["at_a_glance"][0]["headline"] == "Fallback"
        assert output["deep_dives"] == []
        diagnostics = result["validation_diagnostics"]
        assert diagnostics["stage"] == "cross_domain"
        assert diagnostics["issue_count"] == 1
        assert diagnostics["issues"][0]["reason"] == "llm_call_failed"

    def test_no_domain_analysis_returns_empty(self):
        context = {
            "domain_analysis": {},
            "seam_data": {},
            "raw_sources": {"rss": []},
        }
        config = {"llm": {"provider": "fireworks"}}
        result = run(context, config)
        assert "cross_domain_plan" in result
        assert "cross_domain_output" in result
        assert "validation_diagnostics" in result
        assert result["cross_domain_plan"]["schema_version"] == 1
        output = result["cross_domain_output"]
        assert output["at_a_glance"] == []
        diagnostics = result["validation_diagnostics"]
        assert diagnostics["issues"][0]["reason"] == "no_domain_analysis_items"

    @patch("stages.cross_domain.call_llm")
    def test_non_dict_llm_output_returns_full_contract(self, mock_llm):
        mock_llm.side_effect = [
            llm_result({
                "schema_version": 1,
                "cross_domain_connections": [],
                "deep_dives": [],
                "worth_reading": [],
                "rejected_alternatives": [],
            }),
            llm_result("not a dict"),
        ]
        context = {
            "domain_analysis": {
                "geopolitics": {
                    "items": [
                        {
                            "headline": "Fallback",
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

        assert result["cross_domain_plan"]["schema_version"] == 1
        assert result["cross_domain_output"]["at_a_glance"][0]["headline"] == "Fallback"
        assert result["validation_diagnostics"]["issues"][0]["reason"] == (
            "non_dict_llm_output"
        )

    @patch("stages.cross_domain.call_llm")
    def test_contract_issues_are_returned_as_sidecar(self, mock_llm):
        mock_llm.side_effect = [
            llm_result({
                "schema_version": 1,
                "cross_domain_connections": "bad",
                "deep_dives": ["bad"],
                "worth_reading": [],
                "rejected_alternatives": [],
            }),
            llm_result({
                "at_a_glance": [
                    {"item_id": "geo-1", "headline": "Fallback", "links": "bad"}
                ],
                "deep_dives": "bad",
                "cross_domain_connections": [],
                "worth_reading": [],
            }),
        ]
        context = {
            "domain_analysis": {
                "geopolitics": {
                    "items": [
                        {
                            "item_id": "geo-1",
                            "headline": "Fallback",
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

        assert result["cross_domain_output"]["at_a_glance"][0]["headline"] == "Fallback"
        assert result["cross_domain_contract_issues"] == [
            {
                "artifact": "cross_domain_plan",
                "path": "cross_domain_plan.cross_domain_connections",
                "message": "value is not a list",
            },
            {
                "artifact": "cross_domain_plan",
                "path": "cross_domain_plan.deep_dives[0]",
                "message": "plan entry is not an object",
            },
            {
                "artifact": "cross_domain_output",
                "path": "cross_domain_output.at_a_glance[0].links",
                "message": "links is not a list",
            },
            {
                "artifact": "cross_domain_output",
                "path": "cross_domain_output.deep_dives",
                "message": "deep_dives is not a list",
            },
        ]

    @patch("stages.cross_domain.call_llm")
    def test_at_a_glance_cap_enforced(self, mock_llm):
        domain_items = []
        selection = []
        for i in range(10):
            domain_items.append(
                {
                    "item_id": f"cap-{i}",
                    "tag": "war",
                    "headline": f"Test {i}",
                    "facts": f"Facts {i}",
                    "analysis": f"Analysis {i}",
                    "source_depth": "single-source",
                    "links": [],
                }
            )
            selection.append({"item_id": f"cap-{i}", "cross_domain_note": None})
        mock_llm.side_effect = [
            llm_result({
                "schema_version": 1,
                "cross_domain_connections": [],
                "deep_dives": [{"topic": "Test topic", "angle": "Angle", "why_selected": "Why"}],
                "worth_reading": [{"topic": "Long read", "why_worth_reading": "Because"}],
                "rejected_alternatives": [{"topic": "Other", "reason": "Lower priority"}],
            }),
            llm_result({
                "at_a_glance": selection,
                "deep_dives": [],
                "cross_domain_connections": [],
                "worth_reading": [],
            }),
        ]
        context = {
            "domain_analysis": {"geopolitics": {"items": domain_items}},
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
    def test_primary_glance_coverage_added_when_execution_omits_ai(self, mock_llm):
        mock_llm.side_effect = [
            llm_result({
                "schema_version": 1,
                "cross_domain_connections": [],
                "deep_dives": [],
                "worth_reading": [],
                "rejected_alternatives": [],
            }),
            llm_result({
                "at_a_glance": [
                    {"item_id": "war-1", "cross_domain_note": None}
                ],
                "deep_dives": [],
                "cross_domain_connections": [],
                "worth_reading": [],
            }),
        ]
        context = {
            "domain_analysis": {
                "geopolitics": {
                    "items": [
                        {
                            "item_id": "war-1",
                            "tag": "war",
                            "headline": "War item",
                            "facts": "Facts",
                            "analysis": "Analysis",
                            "source_depth": "single-source",
                            "links": [],
                        }
                    ]
                },
                "ai_tech": {
                    "items": [
                        {
                            "item_id": "ai-1",
                            "tag": "AI",
                            "headline": "AI item",
                            "facts": "AI facts",
                            "analysis": "AI analysis",
                            "source_depth": "single-source",
                            "links": [
                                {"url": "https://example.com/ai", "label": "Example"}
                            ],
                            "deep_dive_candidate": False,
                        }
                    ]
                },
            },
            "seam_data": {},
            "raw_sources": {
                "rss": [{"url": "https://example.com/ai", "source": "Example"}]
            },
        }
        config = {
            "llm": {"provider": "fireworks"},
            "digest": {"at_a_glance": {"max_items": 7}},
        }

        result = run(context, config)

        glance = result["cross_domain_output"]["at_a_glance"]
        assert {item["tag"] for item in glance} >= {"war", "ai"}
        assert any(item["headline"] == "AI item" for item in glance)

    @patch("stages.cross_domain.call_llm")
    def test_at_a_glance_links_join_from_desk_item(self, mock_llm):
        # Under the selection-join contract the execute LLM no longer supplies
        # at_a_glance links; they are joined from the desk item, whose links are
        # source-backed by construction (collect_known_urls includes domain
        # analysis links). So desk-item links flow through unchanged.
        mock_llm.side_effect = [
            llm_result({
                "schema_version": 1,
                "cross_domain_connections": [],
                "deep_dives": [{"topic": "Test topic", "angle": "Angle", "why_selected": "Why"}],
                "worth_reading": [{"topic": "Long read", "why_worth_reading": "Because"}],
                "rejected_alternatives": [{"topic": "Other", "reason": "Lower priority"}],
            }),
            llm_result({
                "at_a_glance": [
                    {"item_id": "geo-1", "cross_domain_note": None}
                ],
                "deep_dives": [],
                "cross_domain_connections": [],
                "worth_reading": [],
            }),
        ]
        context = {
            "domain_analysis": {
                "geopolitics": {
                    "items": [
                        {
                            "item_id": "geo-1",
                            "tag": "war",
                            "headline": "Test",
                            "source_depth": "widely-reported",
                            "links": [
                                {"url": "https://example.com/valid", "label": "Valid"},
                            ],
                        }
                    ]
                }
            },
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
    def test_final_validation_keeps_domain_analysis_link(self, mock_llm):
        mock_llm.side_effect = [
            llm_result({
                "schema_version": 1,
                "cross_domain_connections": [],
                "deep_dives": [],
                "worth_reading": [],
                "rejected_alternatives": [],
            }),
            llm_result({
                "at_a_glance": [
                    {"item_id": "ai-1", "cross_domain_note": None}
                ],
                "deep_dives": [],
                "cross_domain_connections": [],
                "worth_reading": [],
            }),
        ]
        context = {
            "domain_analysis": {
                "ai_tech": {
                    "items": [
                        {
                            "item_id": "ai-1",
                            "tag": "ai",
                            "headline": "Test",
                            "source_depth": "single-source",
                            "links": [
                                {"url": "https://analysis.example/story", "label": "A"}
                            ],
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
            llm_result({
                "schema_version": 1,
                "cross_domain_connections": [],
                "deep_dives": [{"topic": "Test topic", "angle": "Angle", "why_selected": "Why"}],
                "worth_reading": [{"topic": "Long read", "why_worth_reading": "Because"}],
                "rejected_alternatives": [{"topic": "Other", "reason": "Lower priority"}],
            }),
            llm_result({
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
            }),
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

    def test_tag_derived_from_desk_of_origin_in_run(self):
        """at_a_glance tag is joined from the desk item, not emitted by the execute LLM."""
        with patch("stages.cross_domain.call_llm") as mock_llm:
            mock_llm.side_effect = [
                llm_result({
                    "schema_version": 1,
                    "cross_domain_connections": [],
                    "deep_dives": [{"topic": "Test topic", "angle": "Angle", "why_selected": "Why"}],
                    "worth_reading": [{"topic": "Long read", "why_worth_reading": "Because"}],
                    "rejected_alternatives": [{"topic": "Other", "reason": "Lower priority"}],
                }),
                llm_result({
                    "at_a_glance": [
                        {"item_id": "geo-1", "cross_domain_note": None}
                    ],
                    "deep_dives": [],
                    "cross_domain_connections": [],
                    "worth_reading": [],
                }),
            ]
            context = {
                "domain_analysis": {
                    "geopolitics": {
                        "items": [
                            {
                                "item_id": "geo-1",
                                "tag": "war",
                                "headline": "Test",
                                "facts": "Facts",
                                "analysis": "Analysis",
                                "source_depth": "single-source",
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
            entry = result["cross_domain_output"]["at_a_glance"][0]
            assert entry["tag"] == "war"
            assert entry["tag_label"] == "Conflict"

    def test_market_context_fallback_from_econ(self):
        """Test that market_context falls back to econ domain analysis."""
        with patch("stages.cross_domain.call_llm") as mock_llm:
            mock_llm.side_effect = [
                llm_result({
                    "schema_version": 1,
                    "cross_domain_connections": [],
                    "deep_dives": [{"topic": "Test topic", "angle": "Angle", "why_selected": "Why"}],
                    "worth_reading": [{"topic": "Long read", "why_worth_reading": "Because"}],
                    "rejected_alternatives": [{"topic": "Other", "reason": "Lower priority"}],
                }),
                llm_result({
                    "at_a_glance": [],
                    "deep_dives": [],
                    "cross_domain_connections": [],
                    "worth_reading": [],
                }),
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

    @patch("stages.cross_domain.call_llm")
    def test_cross_domain_surfaces_llm_usage(self, mock_llm):
        mock_llm.side_effect = [
            llm_result(
                {"deep_dives": [], "worth_reading": [], "cross_domain_connections": []},
                tokens_in=900, tokens_out=120,
            ),
            llm_result(
                {"at_a_glance": [], "deep_dives": [], "worth_reading": [],
                 "cross_domain_connections": []},
                tokens_in=1500, tokens_out=300,
            ),
        ]
        context = {
            "domain_analysis": {
                "econ": {"items": [{"item_id": "e1", "headline": "h",
                                    "facts": "f", "analysis": "a",
                                    "source_depth": "single-source",
                                    "connection_hooks": [], "links": [],
                                    "deep_dive_candidate": False}]}
            },
            "seam_data": {},
            "raw_sources": {"rss": []},
        }
        config = {"llm": {"provider": "fireworks"}, "digest": {}}
        outputs = run(context, config)
        usage = outputs["llm_usage"]
        assert len(usage) == 2 and all(isinstance(u, LLMUsage) for u in usage)
        assert usage[0].tokens_in == 900 and usage[1].tokens_out == 300


def test_domains_bridged_derived_from_further_reading():
    from cross_domain.parse import _derive_domains_bridged

    domain_analysis = {
        "geopolitics_events": {"items": [
            {"item_id": "geopolitics_events-1", "links": [{"url": "https://reuters.com/x"}]},
        ]},
        "defense_space": {"items": [
            {"item_id": "defense_space-1", "links": [{"url": "https://janes.com/y"}]},
        ]},
    }
    result = {"deep_dives": [
        {"headline": "H", "further_reading": [
            {"url": "https://reuters.com/x"}, {"url": "https://janes.com/y"},
        ]},
    ]}
    _derive_domains_bridged(result, domain_analysis)
    assert set(result["deep_dives"][0]["domains_bridged"]) == {"geopolitics_events", "defense_space"}


def test_join_at_a_glance_builds_full_items_from_selection():
    from cross_domain.parse import _join_at_a_glance

    domain_analysis = {
        "ai_tech": {
            "items": [
                {
                    "item_id": "ai_tech-deadbeef",
                    "tag": "ai",
                    "headline": "Frontier model ships",
                    "facts": "Lab X released model Y.",
                    "analysis": "Raises the deployment bar.",
                    "source_depth": "corroborated",
                    "links": [{"url": "https://ex.com/a", "label": "Ex"}],
                    "connection_hooks": [{"entity": "Lab X"}],
                },
            ]
        }
    }
    llm_at_a_glance = [
        {"item_id": "ai_tech-deadbeef", "cross_domain_note": "Ties to the chip-export thread."},
        {"item_id": "ai_tech-MISSING", "cross_domain_note": "typo — should drop"},
    ]
    joined = _join_at_a_glance(llm_at_a_glance, domain_analysis)
    assert len(joined) == 1                       # typo'd id dropped
    item = joined[0]
    assert item["facts"] == "Lab X released model Y."
    assert item["analysis"] == "Raises the deployment bar."
    assert item["tag"] == "ai"
    assert item["tag_label"] == "AI"
    assert item["cross_domain_note"] == "Ties to the chip-export thread."
    assert item["headline"] == "Frontier model ships"
    assert item["links"] == [{"url": "https://ex.com/a", "label": "Ex"}]


_GOLDEN_INPUT = {
    # Execute LLM now emits only a selection; the full item is joined from the desk.
    "at_a_glance": [
        {"item_id": "g1", "cross_domain_note": None},
    ],
    "deep_dives": [
        {"headline": "Deep one", "source_depth": "corroborated", "body": "b",
         "further_reading": [{"url": "https://apnews.com/y"}]},
    ],
    "cross_domain_connections": [],
    "worth_reading": [],
}
_GOLDEN_DOMAIN_ANALYSIS = {
    "ai_tech": {
        "items": [
            {"item_id": "g1", "tag": "ai", "source_depth": "widely-reported",
             "headline": "h1", "facts": "f", "analysis": "a",
             "links": [{"url": "https://reuters.com/x"}]},
        ]
    },
    "econ": {"market_context": "ctx"},
}
_GOLDEN_RAW = {"rss": [{"url": "https://reuters.com/x"}, {"url": "https://apnews.com/y"}]}
_GOLDEN_CONFIG = {"digest": {"at_a_glance": {"max_items": 7}}}

_GOLDEN_PATH = Path(__file__).parent / "golden" / "cross_domain_validated.json"


def _strip_internal(result: dict) -> dict:
    out = json.loads(json.dumps(result))  # deep copy + JSON-normalize
    out.pop("_override_counts", None)
    out.pop("_source_depth_downgrades", None)
    return out


def test_validated_output_matches_golden():
    result = _vo(
        copy.deepcopy(_GOLDEN_INPUT),
        _GOLDEN_DOMAIN_ANALYSIS, _GOLDEN_RAW, _GOLDEN_CONFIG,
    )
    golden = json.loads(_GOLDEN_PATH.read_text())
    assert _strip_internal(result) == golden


class TestSourceDepthRecomputation:
    def test_downgrades_widely_reported_to_single_source(self):
        from cross_domain.parse import _downgrade_same_outlet_depth

        result = {
            "at_a_glance": [
                {
                    "item_id": "x",
                    "source_depth": "widely-reported",
                    "links": [{"url": "https://aljazeera.com/a"}],
                }
            ],
            "deep_dives": [],
        }
        out = _downgrade_same_outlet_depth(result)
        assert out["at_a_glance"][0]["source_depth"] == "single-source"
        assert len(out["_source_depth_downgrades"]) == 1

    def test_corroborated_requires_two_distinct_domains(self):
        from cross_domain.parse import _downgrade_same_outlet_depth

        result = {
            "at_a_glance": [
                {
                    "item_id": "y",
                    "source_depth": "corroborated",
                    "links": [
                        {"url": "https://aljazeera.com/a"},
                        {"url": "https://scmp.com/b"},
                    ],
                }
            ],
            "deep_dives": [],
        }
        out = _downgrade_same_outlet_depth(result)
        assert out["at_a_glance"][0]["source_depth"] == "corroborated"
        assert len(out["_source_depth_downgrades"]) == 0

    def test_widely_reported_requires_four_domains(self):
        from cross_domain.parse import _downgrade_same_outlet_depth

        result = {
            "at_a_glance": [
                {
                    "item_id": "z",
                    "source_depth": "widely-reported",
                    "links": [
                        {"url": "https://a.com/1"},
                        {"url": "https://b.com/2"},
                        {"url": "https://c.com/3"},
                        {"url": "https://d.com/4"},
                    ],
                }
            ],
            "deep_dives": [],
        }
        out = _downgrade_same_outlet_depth(result)
        assert out["at_a_glance"][0]["source_depth"] == "widely-reported"
        assert len(out["_source_depth_downgrades"]) == 0

    def test_deep_dive_uses_further_reading_for_depth(self):
        from cross_domain.parse import _downgrade_same_outlet_depth

        result = {
            "at_a_glance": [],
            "deep_dives": [
                {
                    "headline": "Deep A",
                    "source_depth": "widely-reported",
                    "further_reading": [
                        {"url": "https://a.com/1"},
                        {"url": "https://b.com/2"},
                        {"url": "https://c.com/3"},
                        {"url": "https://d.com/4"},
                    ],
                }
            ],
        }
        out = _downgrade_same_outlet_depth(result)
        assert out["deep_dives"][0]["source_depth"] == "widely-reported"
        assert out["_source_depth_downgrades"] == []


def test_validated_output_counts_overrides():
    # Selection-join: the at_a_glance entry is selected by item_id and the full
    # item (tag/links/source_depth) is joined from the desk item below.
    domain_analysis = {
        "ai_tech": {
            "items": [
                {"item_id": "a", "tag": "ai", "source_depth": "widely-reported",
                 "links": [{"url": "https://x.com/1"}]},
            ]
        }
    }
    result = {
        "at_a_glance": [
            {"item_id": "a", "cross_domain_note": None},
        ],
        "deep_dives": [], "cross_domain_connections": [], "worth_reading": [],
    }
    out = _vo(result, domain_analysis, {"rss": [{"url": "https://x.com/1"}]}, {"digest": {}})
    oc = out["_override_counts"]
    assert oc["recompute_source_depth"] >= 1  # widely-reported single domain -> downgraded
    # tag is derived from the desk item, not normalized/counted any more.
    assert out["at_a_glance"][0]["tag"] == "ai"
    assert out["at_a_glance"][0]["tag_label"] == "AI"
    assert "normalize_tag" not in oc
    assert "tag_label" not in oc


def test_validated_output_counts_ensure_primary_glance_coverage():
    """ensure_primary_glance_coverage counter increments when a fallback item is injected."""
    # Provide an at_a_glance with only "econ" — missing "war" / "ai" / "defense".
    # Provide a geopolitics_events domain result with a non-deep-dive candidate tagged "war".
    result = {
        "at_a_glance": [
            {"item_id": "e1", "tag": "econ", "tag_label": "Economy",
             "source_depth": "single-source", "links": []},
        ],
        "deep_dives": [], "cross_domain_connections": [], "worth_reading": [],
    }
    domain_analysis = {
        "geopolitics_events": {
            "items": [
                {
                    "item_id": "geo1",
                    "tag": "war",
                    "tag_label": "Conflict",
                    "headline": "War headline",
                    "facts": "Some war facts.",
                    "analysis": "Some war analysis.",
                    "source_depth": "corroborated",
                    "deep_dive_candidate": False,
                    "links": [{"url": "https://aljazeera.com/war"}],
                    "connection_hooks": [],
                }
            ]
        }
    }
    raw = {"rss": [{"url": "https://aljazeera.com/war"}]}
    out = _vo(result, domain_analysis, raw, {"digest": {}})
    oc = out["_override_counts"]
    assert oc["ensure_primary_glance_coverage"] >= 1


def test_validated_output_counts_overlap_downgrade():
    """overlap_downgrade counter increments when a deep_dive is downgraded due to phrase overlap.

    A 12-word shared phrase produces 3 distinct 10-word windows, clearing
    _OVERLAP_DOWNGRADE_MIN_WINDOWS (3).  The at_a_glance item and deep_dive
    both contain the phrase, so _downgrade_overlap_depth fires and the
    overlap_downgrade counter should be >= 1.

    The deep_dive is given links from two distinct domains so _downgrade_same_outlet_depth
    (which runs first) does NOT downgrade it — ensuring the item still has
    source_depth "corroborated" when the overlap check runs.
    """
    # 12 distinct words → 3 sliding 10-word windows → triggers overlap downgrade
    shared = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima"
    # The at_a_glance item is selected by item_id; its full body (facts/links) is
    # joined from this desk item so the overlap detector has prose to compare.
    domain_analysis = {
        "geopolitics_events": {
            "items": [
                {
                    "item_id": "ov1",
                    "tag": "war",
                    "headline": "Overlap headline",
                    "facts": shared,
                    "analysis": "",
                    "source_depth": "corroborated",
                    "links": [
                        {"url": "https://reuters.com/a"},
                        {"url": "https://apnews.com/b"},
                    ],
                }
            ]
        }
    }
    result = {
        "at_a_glance": [
            {"item_id": "ov1", "cross_domain_note": None}
        ],
        "deep_dives": [
            {
                "headline": "Deep overlap",
                "body": f"<p>{shared} and additional independent analysis text here.</p>",
                # Two distinct domains → _downgrade_same_outlet_depth leaves this as "corroborated"
                "source_depth": "corroborated",
                "further_reading": [
                    {"url": "https://reuters.com/a"},
                    {"url": "https://bbc.co.uk/deep"},
                ],
            }
        ],
        "cross_domain_connections": [],
        "worth_reading": [],
    }
    raw = {
        "rss": [
            {"url": "https://reuters.com/a"},
            {"url": "https://apnews.com/b"},
            {"url": "https://bbc.co.uk/deep"},
        ]
    }
    out = _vo(result, domain_analysis, raw, {"digest": {}})
    oc = out["_override_counts"]
    assert oc["overlap_downgrade"] >= 1
    # The deep_dive must have been downgraded: corroborated → single-source
    assert out["deep_dives"][0]["source_depth"] == "single-source"
    # Confirm the downgrade log entry uses the constant value
    downgrades = out["_source_depth_downgrades"]
    assert any(d["reason"] == _REASON_PHRASE_OVERLAP for d in downgrades)


class TestOverlapDepthDowngrade:
    def test_downgrades_when_phrase_overlaps_at_a_glance(self):
        from cross_domain.parse import _downgrade_overlap_depth

        # 12 words → 3 distinct 10-word windows, which clears the
        # _OVERLAP_DOWNGRADE_MIN_WINDOWS threshold.
        shared = "one two three four five six seven eight nine ten eleven twelve"
        result = {
            "at_a_glance": [
                {
                    "item_id": "a1",
                    "headline": "Headline A",
                    "facts": shared,
                    "source_depth": "corroborated",
                    "links": [{"url": "https://a.com/1"}, {"url": "https://b.com/2"}],
                }
            ],
            "deep_dives": [
                {
                    "headline": "Deep A",
                    "body": f"<p>{shared} and more unique analysis here</p>",
                    "source_depth": "corroborated",
                    "further_reading": [{"url": "https://c.com/3"}, {"url": "https://d.com/4"}],
                }
            ],
        }
        out = _downgrade_overlap_depth(result)
        assert out["deep_dives"][0]["source_depth"] == "single-source"
        downgrades = out["_source_depth_downgrades"]
        assert len(downgrades) == 1
        assert downgrades[0]["reason"] == _REASON_PHRASE_OVERLAP
        assert downgrades[0]["overlap_count"] >= 3

    def test_single_window_overlap_does_not_downgrade(self):
        """One shared 10-word phrase is below the threshold and must not downgrade."""
        from cross_domain.parse import _downgrade_overlap_depth

        # Exactly 10 words → exactly 1 window. Common journalistic boilerplate
        # like this should not trigger a downgrade on its own.
        shared = "russia launched a large scale missile attack on ukraine today"
        result = {
            "at_a_glance": [
                {
                    "item_id": "a1",
                    "headline": "Headline A",
                    "facts": shared,
                    "source_depth": "corroborated",
                    "links": [{"url": "https://a.com/1"}, {"url": "https://b.com/2"}],
                }
            ],
            "deep_dives": [
                {
                    "headline": "Deep A",
                    "body": f"<p>{shared}, with extensive new sourcing and original analysis "
                            "from independent reporters working on the ground in kyiv</p>",
                    "source_depth": "corroborated",
                    "further_reading": [{"url": "https://c.com/3"}, {"url": "https://d.com/4"}],
                }
            ],
        }
        out = _downgrade_overlap_depth(result)
        assert out["deep_dives"][0]["source_depth"] == "corroborated"
        assert out["_source_depth_downgrades"] == []

    def test_no_downgrade_without_overlap(self):
        from cross_domain.parse import _downgrade_overlap_depth

        result = {
            "at_a_glance": [
                {
                    "item_id": "a1",
                    "headline": "Headline A",
                    "facts": "completely distinct set of words for at a glance",
                    "source_depth": "single-source",
                    "links": [{"url": "https://a.com/1"}],
                }
            ],
            "deep_dives": [
                {
                    "headline": "Deep B",
                    "body": "<p>another entirely different sentence with no shared ten word span</p>",
                    "source_depth": "corroborated",
                    "further_reading": [{"url": "https://c.com/3"}, {"url": "https://d.com/4"}],
                }
            ],
        }
        out = _downgrade_overlap_depth(result)
        assert out["deep_dives"][0]["source_depth"] == "corroborated"
        assert len(out["_source_depth_downgrades"]) == 0

    def test_widely_reported_downgraded_to_corroborated_on_overlap(self):
        from cross_domain.parse import _downgrade_overlap_depth

        # 12 words → 3 windows, clears the overlap threshold.
        shared = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
        result = {
            "at_a_glance": [
                {
                    "item_id": "a1",
                    "headline": "Headline C",
                    "facts": shared,
                    "source_depth": "single-source",
                    "links": [{"url": "https://a.com/1"}],
                }
            ],
            "deep_dives": [
                {
                    "headline": "Deep C",
                    "body": f"<p>{shared} with extensive further background</p>",
                    "source_depth": "widely-reported",
                    "further_reading": [
                        {"url": "https://a.com/1"},
                        {"url": "https://b.com/2"},
                        {"url": "https://c.com/3"},
                        {"url": "https://d.com/4"},
                    ],
                }
            ],
        }
        out = _downgrade_overlap_depth(result)
        assert out["deep_dives"][0]["source_depth"] == "corroborated"
        downgrades = out["_source_depth_downgrades"]
        assert len(downgrades) == 1
        assert downgrades[0]["original_depth"] == "widely-reported"
        assert downgrades[0]["recomputed_depth"] == "corroborated"


class TestFallbackOutputsNoInternalKeyLeak:
    def test_fallback_output_has_no_underscore_keys(self):
        """_fallback_outputs runs _validated_output (which adds internal
        _override_counts / _source_depth_downgrades) when config is set; those
        bookkeeping keys must be popped before the artifact is returned, so the
        saved cross_domain_output never contains _-prefixed keys. Regression for
        the fallback path leaking internal keys into the artifact.
        """
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
        config = {"llm": {"provider": "fireworks"}}
        result = _fallback_outputs(
            domain_analysis,
            reason="llm_error",
            message="boom",
            raw_sources={"rss": []},
            config=config,
        )
        out = result["cross_domain_output"]
        assert not any(k.startswith("_") for k in out)


class TestContractIssueLogging:
    """Malformed LLM output shape (recorded as contract issues) must be visible
    in the logs, not only buried in the persisted artifact."""

    def _context(self):
        return {
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

    @patch("stages.cross_domain.call_llm")
    def test_missing_output_sections_logged(self, mock_llm, caplog):
        mock_llm.side_effect = [
            llm_result({
                "schema_version": 1,
                "cross_domain_connections": [],
                "deep_dives": [],
                "worth_reading": [],
                "rejected_alternatives": [],
            }),
            # execute output omits deep_dives, cross_domain_connections, worth_reading
            llm_result({
                "at_a_glance": [
                    {"tag": "war", "headline": "Test", "facts": "F",
                     "analysis": "A", "source_depth": "single-source", "links": []}
                ],
            }),
        ]
        with caplog.at_level("WARNING", logger="cross_domain.stage"):
            result = run(self._context(), {"llm": {"provider": "fireworks"}})

        # Still produces a valid contract (non-blocking)...
        assert result["cross_domain_output"]["at_a_glance"][0]["tag"] == "war"
        # ...and the drift is both recorded and logged.
        assert any("missing" in i["message"].lower()
                   for i in result["cross_domain_contract_issues"])
        assert "contract" in caplog.text.lower()

    @patch("stages.cross_domain.call_llm")
    def test_clean_output_logs_no_contract_warning(self, mock_llm, caplog):
        mock_llm.side_effect = [
            llm_result({
                "schema_version": 1,
                "cross_domain_connections": [],
                "deep_dives": [],
                "worth_reading": [],
                "rejected_alternatives": [],
            }),
            llm_result({
                "at_a_glance": [],
                "deep_dives": [],
                "cross_domain_connections": [],
                "worth_reading": [],
                "market_context": "ctx",
            }),
        ]
        with caplog.at_level("WARNING", logger="cross_domain.stage"):
            run(self._context(), {"llm": {"provider": "fireworks"}})
        assert "contract" not in caplog.text.lower()


def test_plan_accepts_underproduction_and_caps_overproduction():
    from cross_domain.parse import _normalize_cross_domain_plan

    # Underproduction: 1 connection where 3 requested — accepted as-is.
    under = _normalize_cross_domain_plan(
        {"cross_domain_connections": [{"description": "a"}]},
        deep_dive_count=2, worth_reading_count=3, connection_count=3,
    )
    assert len(under["cross_domain_connections"]) == 1

    # Overproduction: 5 deep_dives where 2 requested — capped to 2.
    over = _normalize_cross_domain_plan(
        {"deep_dives": [{"topic": str(i)} for i in range(5)]},
        deep_dive_count=2, worth_reading_count=3, connection_count=3,
    )
    assert len(over["deep_dives"]) == 2
