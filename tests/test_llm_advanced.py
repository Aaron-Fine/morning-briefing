"""Advanced tests for morning_digest.llm — retry logic and error handling."""

import sys
import os
import json
import time
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from morning_digest.llm import _retry_loop, _parse_response


class TestRetryLoop:
    """Tests for the _retry_loop function."""

    def test_succeeds_on_first_attempt(self):
        call_count = [0]

        def fn():
            call_count[0] += 1
            return "success"

        result = _retry_loop(
            fn, max_retries=2, retryable_errors=(ValueError,), model="test"
        )
        assert result == "success"
        assert call_count[0] == 1

    def test_retries_on_retryable_error(self):
        call_count = [0]

        def fn():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("transient error")
            return "success"

        result = _retry_loop(
            fn, max_retries=3, retryable_errors=(ValueError,), model="test"
        )
        assert result == "success"
        assert call_count[0] == 3

    def test_raises_after_max_retries(self):
        def fn():
            raise ValueError("persistent error")

        with pytest.raises(ValueError, match="persistent error"):
            _retry_loop(fn, max_retries=2, retryable_errors=(ValueError,), model="test")

    def test_does_not_retry_non_retryable_error(self):
        call_count = [0]

        def fn():
            call_count[0] += 1
            raise TypeError("non-retryable")

        with pytest.raises(TypeError):
            _retry_loop(fn, max_retries=2, retryable_errors=(ValueError,), model="test")
        assert call_count[0] == 1

    def test_4xx_client_error_not_retried_even_in_retryable_list(self):
        """Internal safety: 4xx errors are not retried even if caller mistakenly
        includes them in retryable_errors (real callers should never do this)."""
        call_count = [0]

        class Fake4xxError(Exception):
            status_code = 400

        def fn():
            call_count[0] += 1
            raise Fake4xxError("bad request")

        with pytest.raises(Fake4xxError):
            _retry_loop(
                fn, max_retries=2, retryable_errors=(Fake4xxError,), model="test"
            )
        assert call_count[0] == 1  # No retry despite being in retryable_errors

    def test_5xx_server_error_is_retried(self):
        """5xx errors are retried (server-side transient errors)."""
        call_count = [0]

        class Fake5xxError(Exception):
            status_code = 500

        def fn():
            call_count[0] += 1
            if call_count[0] < 2:
                raise Fake5xxError("server error")
            return "success"

        result = _retry_loop(
            fn, max_retries=2, retryable_errors=(Fake5xxError,), model="test"
        )
        assert result == "success"
        assert call_count[0] == 2

    def test_401_auth_error_not_retried(self):
        """401 errors are not retried (client auth failure, not transient)."""
        call_count = [0]

        class FakeAuthError(Exception):
            status_code = 401

        def fn():
            call_count[0] += 1
            raise FakeAuthError("unauthorized")

        with pytest.raises(FakeAuthError):
            _retry_loop(
                fn, max_retries=2, retryable_errors=(FakeAuthError,), model="test"
            )
        assert call_count[0] == 1

    def test_error_without_status_code_is_retried(self):
        """Errors without status_code attribute should be retried."""
        call_count = [0]

        def fn():
            call_count[0] += 1
            if call_count[0] < 2:
                raise RuntimeError("no status code")
            return "success"

        result = _retry_loop(
            fn, max_retries=2, retryable_errors=(RuntimeError,), model="test"
        )
        assert result == "success"
        assert call_count[0] == 2

    def test_exponential_backoff_timing(self):
        """Verify that wait times follow exponential backoff pattern."""
        wait_times = []
        call_count = [0]

        def fn():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("error")
            return "done"

        def mock_sleep(seconds):
            wait_times.append(seconds)

        with patch("morning_digest.llm.time.sleep", mock_sleep):
            _retry_loop(fn, max_retries=3, retryable_errors=(ValueError,), model="test")

        # Expected: 2^(0+1)*5=10, 2^(1+1)*5=20
        assert len(wait_times) == 2
        assert wait_times[0] == 10
        assert wait_times[1] == 20

    def test_max_retries_zero_still_attempts_once(self):
        """With max_retries=0, function should be called exactly once."""
        call_count = [0]

        def fn():
            call_count[0] += 1
            return "ok"

        result = _retry_loop(
            fn, max_retries=0, retryable_errors=(ValueError,), model="test"
        )
        assert result == "ok"
        assert call_count[0] == 1

    def test_max_retries_zero_raises_immediately(self):
        call_count = [0]

        def fn():
            call_count[0] += 1
            raise ValueError("fail")

        with pytest.raises(ValueError):
            _retry_loop(fn, max_retries=0, retryable_errors=(ValueError,), model="test")
        assert call_count[0] == 1


class TestParseResponseAdvanced:
    """Additional edge cases for _parse_response."""

    def test_markdown_fence_with_language(self):
        text = '```json\n{"key": "value"}\n```'
        result = _parse_response(text, json_mode=True, model="test")
        assert result == {"key": "value"}

    def test_markdown_fence_without_language(self):
        text = '```\n{"key": "value"}\n```'
        result = _parse_response(text, json_mode=True, model="test")
        assert result == {"key": "value"}

    def test_markdown_fence_without_closing(self):
        text = '```json\n{"key": "value"}'
        result = _parse_response(text, json_mode=True, model="test")
        assert result == {"key": "value"}

    def test_nested_json(self):
        data = {"outer": {"inner": [1, 2, {"deep": "value"}]}}
        text = json.dumps(data)
        result = _parse_response(text, json_mode=True, model="test")
        assert result == data

    def test_json_array_root(self):
        text = '[{"a": 1}, {"b": 2}]'
        result = _parse_response(text, json_mode=True, model="test")
        assert len(result) == 2

    def test_json_null_value(self):
        text = '{"key": null}'
        result = _parse_response(text, json_mode=True, model="test")
        assert result["key"] is None

    def test_json_boolean_values(self):
        text = '{"a": true, "b": false}'
        result = _parse_response(text, json_mode=True, model="test")
        assert result["a"] is True
        assert result["b"] is False

    def test_json_numeric_values(self):
        text = '{"int": 42, "float": 3.14, "neg": -1}'
        result = _parse_response(text, json_mode=True, model="test")
        assert result["int"] == 42
        assert result["float"] == 3.14
        assert result["neg"] == -1

    def test_json_string_with_escaped_chars(self):
        text = '{"msg": "hello\\nworld\\t!"}'
        result = _parse_response(text, json_mode=True, model="test")
        assert result["msg"] == "hello\nworld\t!"

    def test_invalid_json_raises_decode_error(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_response("not json", json_mode=True, model="test")

    def test_partial_json_raises_decode_error(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_response('{"key": "value"', json_mode=True, model="test")

    def test_non_json_mode_returns_raw_unchanged(self):
        raw = "This is just text, not JSON"
        result = _parse_response(raw, json_mode=False, model="test")
        assert result == raw

    def test_non_json_mode_with_json_content_returns_string(self):
        raw = '{"key": "value"}'
        result = _parse_response(raw, json_mode=False, model="test")
        assert result == raw  # Returns as string, not parsed

    def test_empty_string_json_mode_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_response("", json_mode=True, model="test")

    def test_whitespace_only_json_mode_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_response("   \n\n  ", json_mode=True, model="test")
