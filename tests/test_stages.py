"""Tests for remaining stages: compress, briefing_packet, collect, anomaly."""

import sys
import os
import json
from datetime import date
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.compress import _target_words, _compress_one, run as compress_run
from stages.briefing_packet import (
    _first_two_sentences,
    _build_source_index,
    _build_transcript_summaries,
    _build_connection_hooks,
    _build_metadata,
    _compress_to_budget,
)
from stages.anomaly import (
    _check_category_skew,
    _check_source_absence,
    _dive_is_primary,
    _check_unusual_deep_dives,
    _check_digest_length,
    _check_repeated_phrases,
    _PRIMARY_TAGS,
    _TERTIARY_TAGS,
)


class TestCompressTargetWords:
    def test_small_input_returns_minimum(self):
        assert _target_words(100) == 300

    def test_medium_input_scales_proportionally(self):
        # 1000 * 0.175 = 175, clamped to 300
        assert _target_words(1000) == 300

    def test_large_input_caps_at_maximum(self):
        # 10000 * 0.175 = 1750, clamped to 1200
        assert _target_words(10000) == 1200

    def test_mid_range_returns_proportional(self):
        # 2000 * 0.175 = 350
        assert _target_words(2000) == 350


class TestCompressOne:
    def test_empty_transcript_returns_unchanged(self):
        video = {"title": "Test", "channel": "TestChannel", "transcript": ""}
        result = _compress_one(video, {})
        assert result["title"] == "Test"
        assert "compressed_transcript" not in result

    def test_no_transcript_key_returns_unchanged(self):
        video = {"title": "Test", "channel": "TestChannel"}
        result = _compress_one(video, {})
        assert result["title"] == "Test"

    @patch("stages.compress.call_llm")
    def test_successful_compression(self, mock_llm):
        mock_llm.return_value = "This is a compressed summary."
        video = {
            "title": "Test Video",
            "channel": "TestChannel",
            "transcript": "A" * 5000,
        }
        result = _compress_one(video, {"provider": "fireworks"})
        assert "compressed_transcript" in result
        assert "transcript" not in result
        assert result["category"] == "youtube-analysis"
        mock_llm.assert_called_once()

    @patch("stages.compress.call_llm")
    def test_llm_failure_falls_back_to_raw_words(self, mock_llm):
        mock_llm.side_effect = Exception("API error")
        video = {
            "title": "Test Video",
            "channel": "TestChannel",
            "transcript": "word1 word2 word3 " * 200,
        }
        result = _compress_one(video, {})
        assert "compressed_transcript" in result
        assert len(result["compressed_transcript"].split()) <= 300


class TestCompressRun:
    def test_empty_transcripts_returns_empty_list(self):
        context = {"raw_sources": {"analysis_transcripts": []}}
        result = compress_run(context, {})
        assert result == {"compressed_transcripts": []}

    @patch("stages.compress._compress_one")
    def test_processes_all_transcripts(self, mock_compress):
        mock_compress.return_value = {"compressed": True}
        context = {
            "raw_sources": {
                "analysis_transcripts": [
                    {"transcript": "t1", "title": "v1"},
                    {"transcript": "t2", "title": "v2"},
                ]
            }
        }
        result = compress_run(context, {})
        # Assert on output, not implementation detail (call_count)
        assert len(result["compressed_transcripts"]) == 2
        assert all(ct["compressed"] for ct in result["compressed_transcripts"])


class TestBriefingPacketHelpers:
    def test_first_two_sentences(self):
        text = "First sentence. Second sentence. Third sentence."
        result = _first_two_sentences(text)
        assert result == "First sentence. Second sentence."

    def test_first_two_sentences_single(self):
        text = "Only one sentence."
        result = _first_two_sentences(text)
        assert result == "Only one sentence."

    def test_first_two_sentences_empty(self):
        assert _first_two_sentences("") == ""

    def test_build_source_index(self):
        raw_sources = {
            "rss": [
                {
                    "url": "https://example.com/1",
                    "title": "Article 1",
                    "summary": "Summary of article 1.",
                    "category": "tech",
                    "source": "Example",
                }
            ]
        }
        domain_analysis = {
            "ai_tech": {
                "items": [
                    {
                        "links": [
                            {
                                "url": "https://example.com/1",
                                "label": "Example: Article 1",
                            }
                        ],
                        "headline": "Test",
                    }
                ]
            }
        }
        result = _build_source_index(raw_sources, domain_analysis)
        assert len(result) == 1
        assert result[0]["_referenced"] is True
        assert result[0]["summary"] == "Summary of article 1."

    def test_build_transcript_summaries(self):
        raw_sources = {
            "analysis_transcripts": [
                {"channel": "Ch1", "title": "Video 1", "summary": "Summary 1"},
                {"name": "Ch2", "title": "Video 2", "content": "Content 2"},
            ]
        }
        result = _build_transcript_summaries(raw_sources)
        assert len(result) == 2
        assert result[0]["channel"] == "Ch1"
        assert result[1]["channel"] == "Ch2"

    def test_build_connection_hooks_deduplicates(self):
        domain_analysis = {
            "ai_tech": {
                "items": [
                    {
                        "connection_hooks": [
                            {
                                "entity": "OpenAI",
                                "region": "US",
                                "theme": "AI",
                                "policy": "",
                            },
                        ]
                    }
                ]
            },
            "geopolitics": {
                "items": [
                    {
                        "connection_hooks": [
                            {
                                "entity": "OpenAI",
                                "region": "US",
                                "theme": "AI",
                                "policy": "",
                            },
                            {
                                "entity": "China",
                                "region": "Asia",
                                "theme": "Trade",
                                "policy": "",
                            },
                        ]
                    }
                ]
            },
        }
        result = _build_connection_hooks(domain_analysis)
        assert len(result) == 2  # deduplicated

    def test_build_metadata_uses_run_meta_from_context(self):
        context = {
            "run_meta": {
                "run_date": "2026-04-21",
                "stage_timings": {"collect": 1.2},
                "stage_failures": [{"stage": "weather", "error": "timeout"}],
            },
            "raw_sources": {
                "rss": [
                    {"category": "tech"},
                    {"category": "tech"},
                    {"category": "space"},
                ],
                "analysis_transcripts": [{"title": "One"}],
            },
        }
        config = {
            "pipeline": {
                "stages": [
                    {"name": "analyze_domain", "model": {"model": "model-a"}},
                    {"name": "prepare_weather"},
                ]
            }
        }

        metadata = _build_metadata(context, config)

        assert metadata["date"] == "2026-04-21"
        assert metadata["source_counts"] == {
            "tech": 2,
            "space": 1,
            "transcripts": 1,
        }
        assert metadata["models_used"] == {"analyze_domain": "model-a"}
        assert metadata["stage_timings"] == {"collect": 1.2}
        assert metadata["stage_failures"] == [
            {"stage": "weather", "error": "timeout"}
        ]

    def test_compress_to_budget_under_limit(self):
        packet = {"source_index": [], "transcript_summaries": [], "domain_analyses": {}}
        result = _compress_to_budget(packet)
        assert result is packet  # returned as-is


class TestAnomalyCategorySkew:
    def test_no_anomalies_when_all_primary_tags_present(self):
        items = [
            {"tag": "war", "headline": "A"},
            {"tag": "ai", "headline": "B"},
            {"tag": "defense", "headline": "C"},
        ]
        result = _check_category_skew(items)
        assert result == []

    def test_anomaly_when_primary_tag_missing(self):
        items = [
            {"tag": "war", "headline": "A"},
            {"tag": "ai", "headline": "B"},
        ] * 4  # 8 items total > 5
        result = _check_category_skew(items)
        assert len(result) >= 1
        assert any(a["check"] == "category_skew" for a in result)

    def test_skips_check_when_few_items(self):
        items = [{"tag": "war", "headline": "A"}]
        result = _check_category_skew(items)
        assert result == []


class TestAnomalySourceAbsence:
    def test_no_anomaly_when_category_covered(self):
        raw_sources = {
            "rss": [
                {"url": "https://example.com/1", "category": "ai-tech"},
                {"url": "https://example.com/2", "category": "ai-tech"},
                {"url": "https://example.com/3", "category": "ai-tech"},
            ]
        }
        domain_analysis = {
            "ai_tech": {
                "items": [
                    {
                        "links": [{"url": "https://example.com/1"}],
                        "headline": "Test",
                    }
                ]
            }
        }
        result = _check_source_absence(raw_sources, domain_analysis)
        assert result == []

    def test_anomaly_when_category_not_covered(self):
        raw_sources = {
            "rss": [
                {"url": "https://example.com/1", "category": "econ-trade"},
                {"url": "https://example.com/2", "category": "econ-trade"},
                {"url": "https://example.com/3", "category": "econ-trade"},
            ]
        }
        domain_analysis = {
            "ai_tech": {
                "items": [
                    {
                        "links": [{"url": "https://other.com/1"}],
                        "headline": "Test",
                    }
                ]
            }
        }
        result = _check_source_absence(raw_sources, domain_analysis)
        assert len(result) >= 1
        assert any(a["check"] == "source_absence" for a in result)

    def test_source_absence_summarizes_excess_categories(self):
        categories = [
            "non-western",
            "western-analysis",
            "substack-independent",
            "global-south",
            "perspective-diversity",
            "defense-mil",
        ]
        raw_sources = {
            "rss": [
                {"url": f"https://example.com/{category}/{i}", "category": category}
                for category in categories
                for i in range(3)
            ]
        }
        result = _check_source_absence(raw_sources, {})
        assert any("additional categories" in a["detail"] for a in result)

    def test_source_absence_ignores_non_analysis_consumed_categories(self):
        raw_sources = {
            "rss": [
                {"url": f"https://example.com/regional/{i}", "category": "regional-west"}
                for i in range(3)
            ]
        }
        result = _check_source_absence(raw_sources, {})
        assert result == []


class TestAnomalyDeepDives:
    def test_dive_is_primary_by_domains_bridged(self):
        dive = {"headline": "Test", "domains_bridged": ["geopolitics", "ai_tech"]}
        assert _dive_is_primary(dive) is True

    def test_dive_is_primary_by_tag(self):
        dive = {"headline": "Test", "tag": "war"}
        assert _dive_is_primary(dive) is True

    def test_dive_is_primary_by_keyword(self):
        dive = {"headline": "AI regulation impacts national security"}
        assert _dive_is_primary(dive) is True

    def test_dive_not_primary(self):
        dive = {"headline": "Local community event"}
        assert _dive_is_primary(dive) is False

    def test_unusual_deep_dives_detects_non_primary(self):
        deep_dives = [{"headline": "Local community event"}]
        domain_analysis = {
            "geopolitics": {
                "items": [
                    {"deep_dive_candidate": True, "tag": "war", "headline": "War story"}
                ]
            }
        }
        result = _check_unusual_deep_dives(deep_dives, domain_analysis)
        assert len(result) >= 1
        assert any(a["check"] == "unusual_deep_dive" for a in result)


class TestAnomalyDigestLength:
    @patch("stages.anomaly._ARTIFACTS_BASE")
    def test_no_anomaly_with_normal_count(self, mock_base):
        mock_base.exists.return_value = False
        result = _check_digest_length(10)
        assert result == []

    @patch("stages.anomaly._ARTIFACTS_BASE")
    def test_no_anomaly_when_insufficient_history(self, mock_base):
        mock_base.exists.return_value = True
        mock_base.iterdir.return_value = []
        result = _check_digest_length(10)
        assert result == []


class TestAnomalyRepeatedPhrases:
    def test_detects_repeated_phrase(self):
        cross_domain = {
            "at_a_glance": [
                {
                    "headline": "word1 word2 word3 word4 word5 word6 word7 word8 word9 word10",
                    "context": "extra",
                    "cross_domain_note": "",
                }
            ],
            "deep_dives": [
                {
                    "headline": "word1 word2 word3 word4 word5 word6 word7 word8 word9 word10",
                    "body": "<p>body text</p>",
                }
            ],
        }
        seam_data = {"contested_narratives": []}
        result = _check_repeated_phrases(cross_domain, seam_data)
        assert len(result) >= 1
        assert any(a["check"] == "repeated_phrase" for a in result)

    def test_detects_repeated_phrase_from_facts_analysis(self):
        """Phase 3 items have facts/analysis instead of context."""
        repeated = "word1 word2 word3 word4 word5 word6 word7 word8 word9 word10"
        cross_domain = {
            "at_a_glance": [
                {
                    "headline": "headline",
                    "facts": repeated,
                    "analysis": "some analysis",
                    "cross_domain_note": "",
                }
            ],
            "deep_dives": [
                {
                    "headline": repeated,
                    "body": "<p>body text</p>",
                }
            ],
        }
        seam_data = {"contested_narratives": []}
        result = _check_repeated_phrases(cross_domain, seam_data)
        assert len(result) >= 1
        assert any(a["check"] == "repeated_phrase" for a in result)

    def test_no_false_positive_different_sections(self):
        cross_domain = {
            "at_a_glance": [
                {
                    "headline": "unique phrase one",
                    "context": "",
                    "cross_domain_note": "",
                }
            ],
            "deep_dives": [
                {"headline": "unique phrase two", "body": "<p>different</p>"}
            ],
        }
        seam_data = {"contested_narratives": []}
        result = _check_repeated_phrases(cross_domain, seam_data)
        assert result == []

    def test_repeated_phrase_suppresses_overlapping_noise(self):
        repeated = "word1 word2 word3 word4 word5 word6 word7 word8 word9 word10"
        cross_domain = {
            "at_a_glance": [
                {"headline": repeated, "context": repeated, "cross_domain_note": ""}
            ],
            "deep_dives": [{"headline": repeated, "body": f"<p>{repeated}</p>"}],
        }
        seam_data = {
            "contested_narratives": [{"topic": repeated, "description": repeated}]
        }

        result = _check_repeated_phrases(cross_domain, seam_data)

        assert any(a["check"] == "repeated_phrase" for a in result)
        assert len(result) <= 3
