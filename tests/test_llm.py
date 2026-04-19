"""Tests for morning_digest.llm — LLM client module."""

import sys
import os
import json
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from morning_digest.llm import _parse_response, call_llm


class TestParseResponse:
    def test_non_json_mode_returns_raw_string(self):
        result = _parse_response("Hello world", json_mode=False, model="test")
        assert result == "Hello world"

    def test_json_mode_parses_valid_json(self):
        result = _parse_response('{"key": "value"}', json_mode=True, model="test")
        assert result == {"key": "value"}

    def test_json_mode_strips_markdown_fences(self):
        text = '```json\n{"key": "value"}\n```'
        result = _parse_response(text, json_mode=True, model="test")
        assert result == {"key": "value"}

    def test_json_mode_strips_plain_markdown_fences(self):
        text = '```\n{"key": "value"}\n```'
        result = _parse_response(text, json_mode=True, model="test")
        assert result == {"key": "value"}

    def test_json_mode_raises_on_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_response("not json at all", json_mode=True, model="test")

    def test_json_mode_raises_on_malformed_json(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_response('{"key": "value"', json_mode=True, model="test")

    def test_json_mode_handles_complex_json(self):
        text = json.dumps(
            {
                "at_a_glance": [{"tag": "war", "headline": "Test"}],
                "deep_dives": [],
            }
        )
        result = _parse_response(text, json_mode=True, model="test")
        assert result["at_a_glance"][0]["tag"] == "war"

    def test_json_mode_strips_fences_without_closing(self):
        text = '```json\n{"key": "value"}'
        result = _parse_response(text, json_mode=True, model="test")
        assert result == {"key": "value"}

    def test_json_mode_empty_object(self):
        result = _parse_response("{}", json_mode=True, model="test")
        assert result == {}

    def test_json_mode_empty_array(self):
        result = _parse_response("[]", json_mode=True, model="test")
        assert result == []


class TestCallLlm:
    @patch("morning_digest.llm._call_fireworks")
    def test_defaults_to_fireworks(self, mock_fireworks):
        mock_fireworks.return_value = {"result": "ok"}
        result = call_llm(
            system_prompt="test",
            user_content="test",
            model_config={"provider": "fireworks", "model": "test-model"},
        )
        mock_fireworks.assert_called_once()
        assert result == {"result": "ok"}

    @patch("morning_digest.llm._call_anthropic")
    def test_calls_anthropic_when_specified(self, mock_anthropic):
        mock_anthropic.return_value = {"result": "ok"}
        result = call_llm(
            system_prompt="test",
            user_content="test",
            model_config={"provider": "anthropic", "model": "claude-test"},
        )
        mock_anthropic.assert_called_once()
        assert result == {"result": "ok"}

    @patch("morning_digest.llm._call_fireworks")
    def test_passes_max_retries(self, mock_fireworks):
        mock_fireworks.return_value = "response"
        call_llm(
            system_prompt="test",
            user_content="test",
            model_config={"provider": "fireworks"},
            max_retries=5,
        )
        call_args = mock_fireworks.call_args
        assert call_args.args[3] == 5

    @patch("morning_digest.llm._call_fireworks")
    def test_passes_json_mode(self, mock_fireworks):
        mock_fireworks.return_value = '{"ok": true}'
        call_llm(
            system_prompt="test",
            user_content="test",
            model_config={"provider": "fireworks"},
            json_mode=False,
        )
        call_args = mock_fireworks.call_args
        assert call_args.args[4] is False

    @patch("morning_digest.llm._call_fireworks")
    def test_passes_stream(self, mock_fireworks):
        mock_fireworks.return_value = "response"
        call_llm(
            system_prompt="test",
            user_content="test",
            model_config={"provider": "fireworks"},
            stream=False,
        )
        call_args = mock_fireworks.call_args
        assert call_args.args[5] is False

    @patch("morning_digest.llm._call_fireworks")
    def test_default_provider_is_fireworks(self, mock_fireworks):
        mock_fireworks.return_value = "response"
        call_llm(
            system_prompt="test",
            user_content="test",
            model_config={},
        )
        mock_fireworks.assert_called_once()
