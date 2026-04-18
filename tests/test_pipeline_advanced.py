"""Advanced tests for pipeline.py — retry logic, orchestration, and edge cases."""

import sys
import os
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline import (
    _STAGE_METADATA,
    _get_stage_meta,
    _run_with_retry,
    _artifact_dir,
    _save_artifact,
    _load_artifact,
    _find_most_recent_artifact_dir,
    _prune_artifacts,
    _stage_artifact_key,
    _empty_stage_output,
    _NON_CRITICAL_STAGES,
    _get_stage_model_config,
)


class TestRunWithRetry:
    """Tests for the _run_with_retry function."""

    def test_succeeds_on_first_attempt(self):
        call_count = [0]

        def fn():
            call_count[0] += 1
            return "success"

        result = _run_with_retry(fn, "test_stage", max_retries=2)
        assert result == "success"
        assert call_count[0] == 1

    def test_retries_on_failure_then_succeeds(self):
        call_count = [0]

        def fn():
            call_count[0] += 1
            if call_count[0] < 3:
                raise RuntimeError(f"failure {call_count[0]}")
            return "success"

        with patch("pipeline.time.sleep"):
            result = _run_with_retry(fn, "test_stage", max_retries=3)
        assert result == "success"
        assert call_count[0] == 3

    def test_raises_after_max_retries_exhausted(self):
        def fn():
            raise ValueError("persistent failure")

        with pytest.raises(ValueError, match="persistent failure"):
            with patch("pipeline.time.sleep"):
                _run_with_retry(fn, "test_stage", max_retries=2)

    def test_max_retries_zero_still_calls_once(self):
        call_count = [0]

        def fn():
            call_count[0] += 1
            return "ok"

        result = _run_with_retry(fn, "test_stage", max_retries=0)
        assert result == "ok"
        assert call_count[0] == 1

    def test_max_retries_zero_raises_immediately(self):
        def fn():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            _run_with_retry(fn, "test_stage", max_retries=0)

    def test_exponential_backoff_timing(self):
        wait_times = []
        call_count = [0]

        def fn():
            call_count[0] += 1
            if call_count[0] < 3:
                raise RuntimeError("error")
            return "done"

        with patch("pipeline.time.sleep", side_effect=lambda s: wait_times.append(s)):
            _run_with_retry(fn, "test_stage", max_retries=3)

        # Expected: 2^(0+1)*5=10, 2^(1+1)*5=20
        assert len(wait_times) == 2
        assert wait_times[0] == 10
        assert wait_times[1] == 20

    def test_different_exception_types_retried(self):
        """All exception types are retried (not just specific ones)."""
        call_count = [0]

        def fn():
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("first error")
            elif call_count[0] == 2:
                raise KeyError("second error")
            return "success"

        with patch("pipeline.time.sleep"):
            result = _run_with_retry(fn, "test_stage", max_retries=3)
        assert result == "success"
        assert call_count[0] == 3

    def test_stage_name_in_error_message(self, caplog):
        """Verify stage name appears in retry log messages."""
        call_count = [0]

        def fn():
            call_count[0] += 1
            raise RuntimeError("test error")

        with patch("pipeline.time.sleep"):
            with pytest.raises(RuntimeError):
                _run_with_retry(fn, "my_special_stage", max_retries=1)

        assert "my_special_stage" in caplog.text


class TestGetStageModelConfig:
    """Tests for _get_stage_model_config helper."""

    def test_returns_model_dict(self):
        cfg = {"name": "test", "model": {"provider": "fireworks", "model": "test-model"}}
        result = _get_stage_model_config(cfg)
        assert result == {"provider": "fireworks", "model": "test-model"}

    def test_returns_none_when_no_model(self):
        cfg = {"name": "test"}
        result = _get_stage_model_config(cfg)
        assert result is None

    def test_returns_none_when_model_is_none(self):
        cfg = {"name": "test", "model": None}
        result = _get_stage_model_config(cfg)
        assert result is None

    def test_merges_global_defaults_with_stage_overrides(self):
        cfg = {"name": "prepare_spiritual", "model": {"provider": "anthropic", "model": "x"}}
        config = {"llm": {"max_tokens": 12000, "temperature": 0.4}}
        result = _get_stage_model_config(cfg, stage_name="prepare_spiritual", config=config)
        assert result == {
            "max_tokens": 12000,
            "temperature": 0.4,
            "provider": "anthropic",
            "model": "x",
        }


class TestArtifactDir:
    """Tests for _artifact_dir function."""

    def test_creates_directory(self, tmp_path):
        with patch("pipeline._ARTIFACTS_BASE", tmp_path / "artifacts"):
            result = _artifact_dir("2026-04-15")
        assert result.exists()
        assert result.name == "2026-04-15"

    def test_returns_correct_path(self, tmp_path):
        with patch("pipeline._ARTIFACTS_BASE", tmp_path / "artifacts"):
            result = _artifact_dir("2026-01-01")
        assert str(result).endswith("2026-01-01")


class TestFindMostRecentArtifactDir:
    """Tests for _find_most_recent_artifact_dir function."""

    def test_returns_none_when_base_not_exists(self, tmp_path):
        with patch("pipeline._ARTIFACTS_BASE", tmp_path / "nonexistent"):
            result = _find_most_recent_artifact_dir()
        assert result is None

    def test_returns_most_recent_directory(self, tmp_path):
        base = tmp_path / "artifacts"
        base.mkdir()
        (base / "2026-01-01").mkdir()
        (base / "2026-04-15").mkdir()
        (base / "2026-03-01").mkdir()

        with patch("pipeline._ARTIFACTS_BASE", base):
            result = _find_most_recent_artifact_dir()
        assert result is not None
        assert result.name == "2026-04-15"

    def test_respects_before_date_filter(self, tmp_path):
        base = tmp_path / "artifacts"
        base.mkdir()
        (base / "2026-01-01").mkdir()
        (base / "2026-04-15").mkdir()
        (base / "2026-03-01").mkdir()

        with patch("pipeline._ARTIFACTS_BASE", base):
            result = _find_most_recent_artifact_dir(before_date="2026-04-01")
        assert result is not None
        assert result.name == "2026-03-01"

    def test_skips_non_date_directories(self, tmp_path):
        """Directories with names not exactly 10 chars are skipped."""
        base = tmp_path / "artifacts"
        base.mkdir()
        (base / "2026-04-15").mkdir()
        (base / "some_other_dir").mkdir()  # 12 chars, skipped

        with patch("pipeline._ARTIFACTS_BASE", base):
            result = _find_most_recent_artifact_dir()
        assert result.name == "2026-04-15"

    def test_returns_none_when_no_valid_date_dirs(self, tmp_path):
        """Only non-date-format directories exist."""
        base = tmp_path / "artifacts"
        base.mkdir()
        (base / "short").mkdir()  # 5 chars, skipped
        (base / "very_long_name").mkdir()  # 14 chars, skipped

        with patch("pipeline._ARTIFACTS_BASE", base):
            result = _find_most_recent_artifact_dir()
        assert result is None

    def test_returns_none_when_empty(self, tmp_path):
        base = tmp_path / "artifacts"
        base.mkdir()

        with patch("pipeline._ARTIFACTS_BASE", base):
            result = _find_most_recent_artifact_dir()
        assert result is None


class TestNonCriticalStagesConsistency:
    """Ensure non-critical stages have proper empty output mappings."""

    def test_all_non_critical_stages_have_empty_output(self):
        for stage in _NON_CRITICAL_STAGES:
            output = _empty_stage_output(stage)
            assert output != {}, (
                f"_empty_stage_output('{stage}') returns empty dict — "
                f"downstream stages may crash"
            )

    def test_non_critical_stages_are_valid_names(self):
        for stage in _NON_CRITICAL_STAGES:
            key = _stage_artifact_key(stage)
            assert key != stage or stage == "briefing_packet", (
                f"Non-critical stage '{stage}' has no explicit artifact key mapping"
            )


class TestStageMetadataConsistency:
    def test_known_stages_have_metadata_entries(self):
        known_stages = [
            "collect",
            "compress",
            "analyze_domain",
            "prepare_calendar",
            "prepare_weather",
            "prepare_spiritual",
            "prepare_local",
            "seams",
            "cross_domain",
            "assemble",
            "anomaly",
            "briefing_packet",
            "send",
        ]
        for stage in known_stages:
            assert stage in _STAGE_METADATA

    def test_metadata_context_keys_include_primary_artifact(self):
        for stage in _STAGE_METADATA:
            meta = _get_stage_meta(stage)
            assert meta["artifact_key"] in meta["context_keys"] or stage == "assemble"


class TestStageArtifactKeyMapping:
    """Ensure all stages in the pipeline have explicit artifact key mappings."""

    def test_all_known_stages_mapped(self):
        known_stages = [
            "collect",
            "compress",
            "analyze_domain",
            "prepare_calendar",
            "prepare_weather",
            "prepare_spiritual",
            "prepare_local",
            "seams",
            "cross_domain",
            "assemble",
            "anomaly",
            "briefing_packet",
            "send",
        ]
        for stage in known_stages:
            key = _stage_artifact_key(stage)
            if stage == "briefing_packet":
                continue  # intentionally maps to itself
            assert key != stage, (
                f"Stage '{stage}' falls through to identity fallback"
            )
