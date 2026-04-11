"""Tests for stages/seams.py."""

import sys
import os
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.seams import (
    _build_domain_summary,
    _build_raw_source_summary,
    _build_transcript_summary,
    _collect_known_urls,
    run,
)


class TestBuildDomainSummary:
    def test_basic_domain_analysis(self):
        domain_analysis = {
            "geopolitics": {
                "items": [
                    {
                        "headline": "Test headline",
                        "tag": "war",
                        "source_depth": "widely-reported",
                        "facts": "Test facts",
                        "analysis": "Test analysis",
                        "links": [{"url": "https://example.com", "label": "Example"}],
                    }
                ]
            }
        }
        result = _build_domain_summary(domain_analysis)
        assert "GEOPOLITICS ANALYSIS" in result
        assert "Test headline" in result
        assert "Test facts" in result
        assert "Test analysis" in result

    def test_deep_dive_candidate_flag(self):
        domain_analysis = {
            "geopolitics": {
                "items": [
                    {
                        "headline": "Important story",
                        "tag": "war",
                        "source_depth": "widely-reported",
                        "facts": "Facts",
                        "analysis": "Analysis",
                        "deep_dive_candidate": True,
                        "deep_dive_rationale": "This is important because...",
                        "links": [],
                    }
                ]
            }
        }
        result = _build_domain_summary(domain_analysis)
        assert "[DEEP DIVE CANDIDATE]" in result
        assert "Dive rationale: This is important because..." in result

    def test_connection_hooks_included(self):
        domain_analysis = {
            "ai_tech": {
                "items": [
                    {
                        "headline": "AI Story",
                        "tag": "ai",
                        "source_depth": "single-source",
                        "facts": "Facts",
                        "analysis": "Analysis",
                        "links": [],
                        "connection_hooks": [
                            {
                                "entity": "OpenAI",
                                "region": "US",
                                "theme": "AI Safety",
                                "policy": "",
                            }
                        ],
                    }
                ]
            }
        }
        result = _build_domain_summary(domain_analysis)
        assert "Connection hooks:" in result
        assert "OpenAI" in result

    def test_market_context_from_econ(self):
        domain_analysis = {
            "econ": {
                "items": [
                    {
                        "headline": "Market update",
                        "tag": "econ",
                        "source_depth": "widely-reported",
                        "facts": "Facts",
                        "analysis": "Analysis",
                        "links": [],
                    }
                ],
                "market_context": "Markets are volatile.",
            }
        }
        result = _build_domain_summary(domain_analysis)
        assert "Market context: Markets are volatile." in result

    def test_empty_domain_analysis(self):
        result = _build_domain_summary({})
        assert "(no domain analyses available)" in result

    def test_non_dict_domain_result_skipped(self):
        domain_analysis = {"geopolitics": "not a dict"}
        result = _build_domain_summary(domain_analysis)
        assert "GEOPOLITICS" not in result

    def test_multiple_domains(self):
        domain_analysis = {
            "geopolitics": {
                "items": [
                    {
                        "headline": "G1",
                        "tag": "war",
                        "source_depth": "corroborated",
                        "facts": "F",
                        "analysis": "A",
                        "links": [],
                    }
                ]
            },
            "defense_space": {
                "items": [
                    {
                        "headline": "D1",
                        "tag": "defense",
                        "source_depth": "single-source",
                        "facts": "F",
                        "analysis": "A",
                        "links": [],
                    }
                ]
            },
        }
        result = _build_domain_summary(domain_analysis)
        assert "GEOPOLITICS ANALYSIS" in result
        assert "DEFENSE_SPACE ANALYSIS" in result


class TestBuildRawSourceSummary:
    def test_basic_rss_sources(self):
        raw_sources = {
            "rss": [
                {
                    "source": "Example",
                    "title": "Test Article",
                    "summary": "This is a test summary.",
                    "category": "tech",
                    "url": "https://example.com/1",
                }
            ]
        }
        result = _build_raw_source_summary(raw_sources)
        assert "TECH (1 items)" in result
        assert "Test Article" in result
        assert "https://example.com/1" in result

    def test_groups_by_category(self):
        raw_sources = {
            "rss": [
                {"source": "A", "title": "T1", "summary": "S1", "category": "tech"},
                {"source": "B", "title": "T2", "summary": "S2", "category": "econ"},
                {"source": "C", "title": "T3", "summary": "S3", "category": "tech"},
            ]
        }
        result = _build_raw_source_summary(raw_sources)
        assert "TECH (2 items)" in result
        assert "ECON (1 items)" in result

    def test_reliability_note(self):
        raw_sources = {
            "rss": [
                {
                    "source": "Example",
                    "title": "Test",
                    "summary": "Summary",
                    "category": "tech",
                    "reliability": "low",
                }
            ]
        }
        result = _build_raw_source_summary(raw_sources)
        assert "[low]" in result

    def test_no_raw_source_data(self):
        result = _build_raw_source_summary({})
        assert "(no raw source data)" in result

    def test_caps_per_category(self):
        raw_sources = {
            "rss": [
                {
                    "source": f"Source{i}",
                    "title": f"T{i}",
                    "summary": f"S{i}",
                    "category": "tech",
                }
                for i in range(20)
            ]
        }
        result = _build_raw_source_summary(raw_sources)
        # Should cap at 12 per category - count actual source entries in output
        # Each entry appears as "Source{i}: T{i}"
        entry_count = result.count(": T")  # Each entry has ": T" from "Source{i}: T{i}"
        assert entry_count <= 12, f"Expected <=12 entries, got {entry_count}"


class TestBuildTranscriptSummary:
    def test_basic_transcripts(self):
        transcripts = [
            {
                "channel": "Ch1",
                "title": "Video 1",
                "compressed_transcript": "Compressed text",
            },
        ]
        result = _build_transcript_summary(transcripts)
        assert "Ch1" in result
        assert "Video 1" in result

    def test_fallback_to_transcript_key(self):
        transcripts = [
            {
                "channel": "Ch1",
                "title": "Video 1",
                "transcript": "Full transcript text",
            },
        ]
        result = _build_transcript_summary(transcripts)
        assert "Full transcript text" in result

    def test_truncates_long_text(self):
        long_text = "A" * 1000
        transcripts = [
            {"channel": "Ch1", "title": "Video 1", "compressed_transcript": long_text},
        ]
        result = _build_transcript_summary(transcripts)
        assert len(result) < len(long_text)
        assert "..." in result

    def test_no_transcripts(self):
        result = _build_transcript_summary([])
        assert "(no transcripts)" in result


class TestCollectKnownUrls:
    def test_collects_from_raw_sources(self):
        raw_sources = {
            "rss": [{"url": "https://example.com/1"}],
            "local_news": [{"url": "https://local.com/1"}],
            "analysis_transcripts": [{"url": "https://yt.com/1"}],
        }
        domain_analysis = {}
        result = _collect_known_urls(raw_sources, domain_analysis)
        assert "https://example.com/1" in result
        assert "https://local.com/1" in result
        assert "https://yt.com/1" in result

    def test_collects_from_domain_analysis(self):
        raw_sources = {"rss": []}
        domain_analysis = {
            "geopolitics": {
                "items": [
                    {
                        "links": [{"url": "https://domain.com/1", "label": "Domain"}],
                    }
                ]
            }
        }
        result = _collect_known_urls(raw_sources, domain_analysis)
        assert "https://domain.com/1" in result


class TestSeamsRun:
    @patch("stages.seams.call_llm")
    def test_successful_run(self, mock_llm):
        mock_llm.return_value = {
            "contested_narratives": [
                {
                    "topic": "Test topic",
                    "description": "Test description",
                    "sources_a": "Source A",
                    "sources_b": "Source B",
                    "analytical_significance": "Significant",
                    "links": [{"url": "https://example.com", "label": "Example"}],
                },
                {
                    "topic": "Test topic 2",
                    "description": "Test description 2",
                    "sources_a": "Source A",
                    "sources_b": "Source B",
                    "analytical_significance": "Significant",
                    "links": [{"url": "https://example.com", "label": "Example"}],
                },
            ],
            "coverage_gaps": [
                {
                    "topic": "Gap topic",
                    "description": "Gap description",
                    "present_in": "tech",
                    "absent_from": "geopolitics",
                    "links": [],
                }
            ],
            "key_assumptions": [],
        }
        context = {
            "domain_analysis": {
                "geopolitics": {
                    "items": [
                        {
                            "headline": "Test",
                            "tag": "war",
                            "source_depth": "widely-reported",
                            "facts": "Facts",
                            "analysis": "Analysis",
                            "links": [
                                {"url": "https://example.com", "label": "Example"}
                            ],
                        }
                    ]
                }
            },
            "raw_sources": {
                "rss": [
                    {
                        "source": "Example",
                        "title": "Test Article",
                        "summary": "Summary",
                        "category": "tech",
                        "url": "https://example.com/1",
                    }
                ]
            },
            "compressed_transcripts": [],
        }
        config = {"llm": {"seam_detection": {"provider": "anthropic"}}}
        result = run(context, config)
        assert "seam_data" in result
        seam_data = result["seam_data"]
        assert len(seam_data["contested_narratives"]) == 2
        assert len(seam_data["coverage_gaps"]) == 1
        assert seam_data["seam_count"] == 3
        assert seam_data["quiet_day"] is False

    @patch("stages.seams.call_llm")
    def test_quiet_day_detection(self, mock_llm):
        mock_llm.return_value = {
            "contested_narratives": [],
            "coverage_gaps": [],
            "key_assumptions": [],
        }
        context = {
            "domain_analysis": {"geopolitics": {"items": []}},
            "raw_sources": {"rss": []},
            "compressed_transcripts": [],
        }
        config = {"llm": {}}
        result = run(context, config)
        assert result["seam_data"]["quiet_day"] is True
        assert result["seam_data"]["seam_count"] == 0

    @patch("stages.seams.call_llm")
    def test_llm_failure_returns_empty(self, mock_llm):
        mock_llm.side_effect = Exception("API error")
        context = {
            "domain_analysis": {"geopolitics": {"items": []}},
            "raw_sources": {"rss": []},
            "compressed_transcripts": [],
        }
        config = {"llm": {}}
        result = run(context, config)
        assert "seam_data" in result
        seam_data = result["seam_data"]
        assert seam_data["contested_narratives"] == []
        assert seam_data["coverage_gaps"] == []
        assert seam_data["key_assumptions"] == []
        assert seam_data["seam_count"] == 0
        assert seam_data["quiet_day"] is True

    @patch("stages.seams.call_llm")
    def test_missing_fields_get_defaults(self, mock_llm):
        mock_llm.return_value = {}
        context = {
            "domain_analysis": {"geopolitics": {"items": []}},
            "raw_sources": {"rss": []},
            "compressed_transcripts": [],
        }
        config = {"llm": {}}
        result = run(context, config)
        seam_data = result["seam_data"]
        assert seam_data["contested_narratives"] == []
        assert seam_data["coverage_gaps"] == []
        assert seam_data["key_assumptions"] == []
        assert seam_data["seam_count"] == 0

    @patch("stages.seams.call_llm")
    def test_url_validation_applied(self, mock_llm):
        mock_llm.return_value = {
            "contested_narratives": [
                {
                    "topic": "Test",
                    "description": "Desc",
                    "sources_a": "A",
                    "sources_b": "B",
                    "analytical_significance": "Sig",
                    "links": [
                        {"url": "https://example.com/valid", "label": "Valid"},
                        {"url": "https://unknown.com/fake", "label": "Fake"},
                    ],
                }
            ],
            "coverage_gaps": [],
            "key_assumptions": [],
        }
        context = {
            "domain_analysis": {"geopolitics": {"items": []}},
            "raw_sources": {
                "rss": [
                    {
                        "url": "https://example.com/valid",
                        "source": "Example",
                        "title": "T",
                        "summary": "S",
                        "category": "tech",
                    }
                ]
            },
            "compressed_transcripts": [],
        }
        config = {"llm": {}}
        result = run(context, config)
        links = result["seam_data"]["contested_narratives"][0]["links"]
        # validate_urls strips unknown URLs by setting url to ""
        # So we should have 2 links, one with empty url
        assert len(links) == 2
        assert links[0]["url"] == "https://example.com/valid"
        assert links[1]["url"] == ""
