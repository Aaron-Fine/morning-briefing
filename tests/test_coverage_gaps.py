"""Tests for stages/coverage_gaps.py — coverage gap detection diagnostic."""

import sys
import os
import json
import tempfile
from unittest.mock import patch
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.coverage_gaps import (
    _build_domain_summary,
    _build_plan_summary,
    _build_recurring_context,
    _empty_result,
    _normalize_result,
    _load_recent_history,
    _append_history,
    run,
)


class TestBuildDomainSummary:
    def test_formats_domain_items(self):
        analysis = {
            "geopolitics": {
                "items": [
                    {"tag": "war", "headline": "Conflict escalates"},
                    {"tag": "domestic", "headline": "Policy shift"},
                ]
            },
            "ai_tech": {"items": []},
        }
        result = _build_domain_summary(analysis)
        assert "GEOPOLITICS (2 items)" in result
        assert "Conflict escalates" in result
        assert "AI_TECH: (no items)" in result

    def test_empty_analysis(self):
        assert _build_domain_summary({}) == "(no domain analyses available)"

    def test_non_dict_domain_skipped(self):
        result = _build_domain_summary({"bad": "not a dict"})
        assert result == "(no domain analyses available)"


class TestBuildPlanSummary:
    def test_formats_plan(self):
        plan = {
            "deep_dives": [{"topic": "AI governance"}],
            "worth_reading": [{"topic": "Trade analysis"}],
        }
        result = _build_plan_summary(plan)
        assert "AI governance" in result
        assert "Trade analysis" in result

    def test_empty_plan(self):
        assert "(no editorial plan available)" in _build_plan_summary({})
        assert "(no editorial plan available)" in _build_plan_summary(None)


class TestEmptyResult:
    def test_schema_shape(self):
        result = _empty_result("2026-04-18")
        assert result["schema_version"] == 1
        assert result["date"] == "2026-04-18"
        assert result["gaps"] == []
        assert result["recurring_patterns"] == []


class TestNormalizeResult:
    def test_drops_unexpected_top_level_fields(self):
        result = _normalize_result(
            {
                "schema_version": 99,
                "date": "2026-04-18",
                "gaps": [{"topic": "Gap", "description": "Desc", "significance": "high"}],
                "recurring_patterns": ["Repeated miss"],
                "topic": "stray",
                "description": "stray",
            },
            "2026-04-18",
        )
        assert set(result.keys()) == {
            "schema_version",
            "date",
            "gaps",
            "recurring_patterns",
        }
        assert result["schema_version"] == 1

    def test_normalizes_gap_items(self):
        result = _normalize_result(
            {
                "gaps": [
                    {
                        "topic": " Gap ",
                        "description": " Desc ",
                        "significance": "urgent",
                        "hypothesis": " Why ",
                        "suggested_source_category": " Cat ",
                    }
                ]
            },
            "2026-04-18",
        )
        assert result["gaps"] == [
            {
                "topic": "Gap",
                "description": "Desc",
                "significance": "low",
                "hypothesis": "Why",
                "suggested_source_category": "Cat",
            }
        ]

    def test_drops_blank_gap_items(self):
        result = _normalize_result(
            {
                "gaps": [
                    {"topic": "", "description": ""},
                    {"topic": "Gap", "description": "Desc"},
                ]
            },
            "2026-04-18",
        )
        assert result["gaps"] == [
            {
                "topic": "Gap",
                "description": "Desc",
                "significance": "low",
                "hypothesis": "",
                "suggested_source_category": "",
            }
        ]


class TestHistory:
    def test_append_and_load(self, tmp_path):
        history_file = tmp_path / "coverage_gaps_history.jsonl"
        entry = _empty_result("2026-04-18")
        entry["gaps"] = [{"topic": "Test gap"}]

        with patch("stages.coverage_gaps._HISTORY_FILE", history_file):
            with patch("stages.coverage_gaps._OUTPUT_DIR", tmp_path):
                _append_history(entry)
                _append_history(entry)
                history = _load_recent_history()

        assert len(history) == 2
        assert history[0]["gaps"][0]["topic"] == "Test gap"

    def test_load_missing_file(self, tmp_path):
        missing = tmp_path / "nonexistent.jsonl"
        with patch("stages.coverage_gaps._HISTORY_FILE", missing):
            assert _load_recent_history() == []

    def test_load_caps_at_max_entries(self, tmp_path):
        history_file = tmp_path / "history.jsonl"
        with open(history_file, "w") as f:
            for i in range(20):
                f.write(json.dumps({"date": f"2026-04-{i:02d}", "gaps": []}) + "\n")

        with patch("stages.coverage_gaps._HISTORY_FILE", history_file):
            result = _load_recent_history(max_entries=5)
        assert len(result) == 5


class TestBuildRecurringContext:
    def test_no_history(self):
        result = _build_recurring_context([])
        assert "No prior" in result

    def test_with_history(self):
        history = [
            {"date": "2026-04-17", "gaps": [{"topic": "Supply chain", "description": "Missing"}]},
            {"date": "2026-04-16", "gaps": []},
        ]
        result = _build_recurring_context(history)
        assert "Supply chain" in result
        assert "2026-04-17" in result


class TestRunStage:
    def _make_context(self):
        return {
            "domain_analysis": {
                "geopolitics": {
                    "items": [{"tag": "war", "headline": "Test"}]
                }
            },
            "cross_domain_plan": {
                "deep_dives": [{"topic": "Test topic"}]
            },
        }

    @patch("stages.coverage_gaps.call_llm")
    @patch("stages.coverage_gaps._append_history")
    def test_successful_run(self, mock_history, mock_llm):
        mock_llm.return_value = {
            "schema_version": 1,
            "date": "2026-04-18",
            "gaps": [
                {
                    "topic": "Semiconductor supply",
                    "description": "No coverage of chip export controls",
                    "significance": "high",
                    "hypothesis": "No source in that category",
                    "suggested_source_category": "ai-tech",
                }
            ],
            "recurring_patterns": [],
        }
        result = run(self._make_context(), {}, {"provider": "fireworks"})
        assert "coverage_gaps" in result
        assert len(result["coverage_gaps"]["gaps"]) == 1
        mock_history.assert_called_once()

    @patch("stages.coverage_gaps.call_llm")
    @patch("stages.coverage_gaps._append_history")
    def test_llm_failure_returns_empty(self, mock_history, mock_llm):
        mock_llm.side_effect = Exception("API error")
        result = run(self._make_context(), {}, {"provider": "fireworks"})
        assert result["coverage_gaps"]["gaps"] == []
        mock_history.assert_not_called()

    def test_no_domain_analysis_returns_empty(self):
        result = run({}, {})
        assert result["coverage_gaps"]["gaps"] == []

    @patch("stages.coverage_gaps.call_llm")
    @patch("stages.coverage_gaps._append_history")
    def test_caps_gaps_at_five(self, mock_history, mock_llm):
        mock_llm.return_value = {
            "gaps": [{"topic": f"Gap {i}"} for i in range(10)],
            "recurring_patterns": [],
        }
        result = run(self._make_context(), {}, {"provider": "fireworks"})
        assert len(result["coverage_gaps"]["gaps"]) == 5

    @patch("stages.coverage_gaps.call_llm")
    @patch("stages.coverage_gaps._append_history")
    def test_non_dict_result_normalized(self, mock_history, mock_llm):
        mock_llm.return_value = "not a dict"
        result = run(self._make_context(), {}, {"provider": "fireworks"})
        assert result["coverage_gaps"]["gaps"] == []
