"""Tests for stages/prepare_spiritual.py — LLM reflection generation with fallback."""

import sys
import os
import logging
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.prepare_spiritual import run, _SYSTEM_PROMPT


class TestPrepareSpiritualRun:
    @pytest.fixture(autouse=True)
    def no_weekly_artifact(self, monkeypatch):
        monkeypatch.setattr(
            "stages.prepare_spiritual._find_latest_weekly_artifact",
            lambda today=None: None,
        )

    def _make_cfm_data(self):
        return {
            "reading": "Mosiah 1-3",
            "title": "King Benjamin's Teachings",
            "key_scripture": "Mosiah 2:17",
            "scripture_text": "When ye are in the service of your fellow beings ye are only in the service of your God.",
            "date_range": "Jan 1-7",
            "lesson_url": "https://example.com/lesson",
            "lesson_num": 1,
        }

    def _make_config(self):
        return {"llm": {"provider": "fireworks"}}

    def _make_context(self, cfm_data=None):
        if cfm_data is None:
            cfm_data = self._make_cfm_data()
        return {"raw_sources": {"come_follow_me": cfm_data}}

    @patch("stages.prepare_spiritual.call_llm")
    def test_successful_llm_reflection(self, mock_llm):
        mock_llm.return_value = "This is a thoughtful reflection."
        result = run(
            self._make_context(),
            self._make_config(),
            model_config={"provider": "fireworks"},
        )
        assert result["spiritual"]["reflection"] == "This is a thoughtful reflection."
        mock_llm.assert_called_once()

    @patch("stages.prepare_spiritual.call_llm")
    def test_llm_exception_falls_back_to_scripture_text(self, mock_llm, caplog):
        mock_llm.side_effect = Exception("API error")
        with caplog.at_level(logging.WARNING):
            result = run(
                self._make_context(),
                self._make_config(),
                model_config={"provider": "fireworks"},
            )
        assert "LLM call failed" in caplog.text
        assert (
            result["spiritual"]["reflection"] == self._make_cfm_data()["scripture_text"]
        )

    def test_no_model_config_uses_scripture_text(self, caplog):
        with caplog.at_level(logging.INFO):
            result = run(self._make_context(), {})
        assert "no model config" in caplog.text
        assert (
            result["spiritual"]["reflection"] == self._make_cfm_data()["scripture_text"]
        )

    def test_missing_cfm_data_returns_empty(self, caplog):
        context = {"raw_sources": {}}
        with caplog.at_level(logging.WARNING):
            result = run(context, self._make_config())
        assert result["spiritual"] == {}
        assert "no Come Follow Me data" in caplog.text

    def test_cfm_without_reading_returns_empty(self):
        context = {"raw_sources": {"come_follow_me": {"title": "No reading"}}}
        result = run(context, self._make_config())
        assert result["spiritual"] == {}

    def test_cfm_with_empty_reading_returns_empty(self):
        context = {"raw_sources": {"come_follow_me": {"reading": ""}}}
        result = run(context, self._make_config())
        assert result["spiritual"] == {}

    @patch("stages.prepare_spiritual.call_llm")
    def test_reflection_stripped_of_whitespace(self, mock_llm):
        mock_llm.return_value = "  Reflection with spaces.  "
        result = run(
            self._make_context(),
            self._make_config(),
            model_config={"provider": "fireworks"},
        )
        assert result["spiritual"]["reflection"] == "Reflection with spaces."

    @patch("stages.prepare_spiritual.call_llm")
    def test_empty_llm_response_falls_back_to_scripture(self, mock_llm):
        mock_llm.return_value = ""
        result = run(
            self._make_context(),
            self._make_config(),
            model_config={"provider": "fireworks"},
        )
        assert (
            result["spiritual"]["reflection"] == self._make_cfm_data()["scripture_text"]
        )

    @patch("stages.prepare_spiritual.call_llm")
    def test_passes_correct_prompt_content(self, mock_llm):
        mock_llm.return_value = "Reflection"
        cfm = self._make_cfm_data()
        run(
            self._make_context(cfm),
            self._make_config(),
            model_config={"provider": "fireworks"},
        )
        call_args = mock_llm.call_args
        assert call_args[0][0] == _SYSTEM_PROMPT
        user_content = call_args[0][1]
        assert cfm["reading"] in user_content
        assert cfm["title"] in user_content
        assert cfm["key_scripture"] in user_content
        assert cfm["scripture_text"] in user_content

    @patch("stages.prepare_spiritual.call_llm")
    def test_passes_correct_llm_params(self, mock_llm):
        mock_llm.return_value = "Reflection"
        run(
            self._make_context(),
            self._make_config(),
            model_config={"provider": "fireworks"},
        )
        call_kwargs = mock_llm.call_args[1]
        assert call_kwargs["max_retries"] == 1
        assert call_kwargs["json_mode"] is False
        assert call_kwargs["stream"] is True

    def test_preserves_all_cfm_fields_in_output(self):
        cfm = self._make_cfm_data()
        result = run(self._make_context(cfm), {})
        assert result["spiritual"]["reading"] == cfm["reading"]
        assert result["spiritual"]["title"] == cfm["title"]
        assert result["spiritual"]["key_scripture"] == cfm["key_scripture"]
        assert result["spiritual"]["scripture_text"] == cfm["scripture_text"]
        assert result["spiritual"]["date_range"] == cfm["date_range"]
        assert result["spiritual"]["lesson_url"] == cfm["lesson_url"]
        assert result["spiritual"]["lesson_num"] == cfm["lesson_num"]

    def test_missing_cfm_fields_handled_gracefully(self):
        context = {"raw_sources": {"come_follow_me": {"reading": "Test"}}}
        result = run(context, {})
        assert result["spiritual"]["reading"] == "Test"
        assert result["spiritual"]["reflection"] == ""

    @patch("stages.prepare_spiritual.call_llm")
    def test_uses_weekly_artifact_focus(self, mock_llm, monkeypatch):
        mock_llm.return_value = "Weekly reflection."
        weekly = {
            "week_start": "2026-01-05",
            "cfm_range": "Mosiah 1-3",
            "weekly_purpose": "Purpose",
            "daily_foci": [
                {
                    "id": "focus-1",
                    "text_ref": "Mosiah 2:17",
                    "guide_excerpt": "Service is covenantal, not performative.",
                }
            ],
            "misuses": [],
            "applications": [],
            "conspicuous_absences": [],
            "proposed_sequence": {"monday": "focus-1"},
        }
        monkeypatch.setattr(
            "stages.prepare_spiritual._find_latest_weekly_artifact",
            lambda today=None: weekly,
        )
        monkeypatch.setattr(
            "stages.prepare_spiritual.now_local",
            lambda: MagicMock(date=lambda: __import__("datetime").date(2026, 1, 5)),
        )

        result = run(
            self._make_context(),
            self._make_config(),
            model_config={"provider": "fireworks"},
        )

        assert result["spiritual"]["reflection"] == "Weekly reflection."
        assert result["spiritual"]["focus_id"] == "focus-1"
        assert "Service is covenantal" in mock_llm.call_args[0][1]
