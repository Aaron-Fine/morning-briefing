"""Tests for morning_digest.llm — LLM client module."""

import sys
import os
import json
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from morning_digest.llm import _fireworks_call, _parse_response, _usage_tuple, call_llm, LLMResult, LLMUsage


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

    @patch("morning_digest.llm._capture_prompt", side_effect=OSError("disk full"))
    @patch("morning_digest.llm._call_fireworks")
    def test_capture_oserror_is_swallowed(self, mock_fireworks, _mock_capture, caplog):
        """Prompt capture is best-effort: a non-FileExistsError OSError (disk
        full, permission) must be logged and swallowed, never propagated to fail
        a real run."""
        mock_fireworks.return_value = "response"
        with caplog.at_level("WARNING"):
            result = call_llm(
                system_prompt="test",
                user_content="test",
                model_config={
                    "provider": "fireworks",
                    "_obs": {"stage": "demo", "capture_dir": "/tmp/cap"},
                },
            )
        assert result == "response"
        mock_fireworks.assert_called_once()
        assert any("prompt capture failed" in r.message for r in caplog.records)


def _fireworks_resp(content, prompt_tokens=12, completion_tokens=7, cached_tokens=3):
    # Verified shape (2026-05-30): usage has prompt_tokens_details.cached_tokens.
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    resp.usage.prompt_tokens_details.cached_tokens = cached_tokens
    return resp


@patch("morning_digest.llm._fireworks_client")
def test_call_llm_returns_llmresult_with_usage(mock_client):
    mock_client.return_value.chat.completions.create.return_value = _fireworks_resp(
        '{"ok": true}'
    )
    out = call_llm("sys", "user", {"provider": "fireworks", "model": "m", "max_tokens": 100}, stream=False)
    assert isinstance(out, LLMResult)
    assert out.value == {"ok": True}
    assert out.usage == LLMUsage("m", "fireworks", tokens_in=12, tokens_out=7, tokens_cached=3)


@patch("morning_digest.llm._fireworks_client")
def test_fireworks_stream_usage_from_final_chunk(mock_client):
    usage_chunk = MagicMock(
        choices=[],
        usage=MagicMock(prompt_tokens=100, completion_tokens=40,
                        prompt_tokens_details=MagicMock(cached_tokens=12)),
    )
    text_chunk = MagicMock()
    text_chunk.choices = [MagicMock()]
    text_chunk.choices[0].delta.content = "hello"
    text_chunk.usage = None
    stream_cm = MagicMock()
    stream_cm.__enter__.return_value = iter([text_chunk, usage_chunk])
    stream_cm.__exit__.return_value = False
    mock_client.return_value.chat.completions.create.return_value = stream_cm
    out = call_llm("s", "u", {"provider": "fireworks", "model": "m", "max_tokens": 8000}, json_mode=False)
    assert out.value == "hello"
    assert out.usage.tokens_in == 100 and out.usage.tokens_out == 40
    assert out.usage.tokens_cached == 12


@patch("morning_digest.llm._anthropic_client")
def test_anthropic_usage(mock_client):
    msg = MagicMock()
    msg.content = [MagicMock(text="result text")]
    msg.usage = MagicMock(input_tokens=33, output_tokens=9)
    mock_client.return_value.messages.create.return_value = msg
    out = call_llm("s", "u", {"provider": "anthropic", "model": "claude-x"}, json_mode=False, stream=False)
    assert out.value == "result text"
    assert out.usage == LLMUsage("claude-x", "anthropic", 33, 9)


def test_usage_tuple_handles_missing_usage():
    assert _usage_tuple(None) == (None, None, None)

    class _NoDetails:
        prompt_tokens = 5
        completion_tokens = 2
        # no prompt_tokens_details attribute

    assert _usage_tuple(_NoDetails()) == (5, 2, None)


class _FakeStreamResponse:
    def __init__(self, chunks):
        self._chunks = chunks

    def __enter__(self):
        return iter(self._chunks)

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeChunk:
    def __init__(self, *, content=None, reasoning_content=None, has_choices=True, usage=None):
        self.choices = [] if not has_choices else [
            MagicMock(
                delta=MagicMock(
                    content=content,
                    reasoning_content=reasoning_content,
                )
            )
        ]
        self.usage = usage


class TestFireworksCall:
    def test_stream_returns_content_only(self):
        client = MagicMock()
        client.chat.completions.create.return_value = _FakeStreamResponse(
            [
                _FakeChunk(reasoning_content="hidden thinking"),
                _FakeChunk(content='{"ok":'),
                _FakeChunk(content=' true}'),
            ]
        )

        text, tokens_in, tokens_out, tokens_cached = _fireworks_call(client, {"model": "test"}, stream=True)

        assert text == '{"ok": true}'
        assert tokens_in is None and tokens_out is None and tokens_cached is None

    def test_stream_does_not_fallback_to_reasoning_content(self):
        client = MagicMock()
        client.chat.completions.create.return_value = _FakeStreamResponse(
            [
                _FakeChunk(reasoning_content="step 1"),
                _FakeChunk(reasoning_content="step 2"),
            ]
        )

        text, tokens_in, tokens_out, tokens_cached = _fireworks_call(client, {"model": "test"}, stream=True)

        assert text == ""
