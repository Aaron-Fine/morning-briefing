"""Tests for pipeline.py — orchestration layer."""

import sys
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline import (
    _stage_artifact_key,
    _empty_stage_output,
    _NON_CRITICAL_STAGES,
    _save_artifact,
    _load_artifact,
    _prune_artifacts,
)


class TestStageArtifactKey:
    def test_known_stages_return_explicit_keys(self):
        mappings = {
            "collect": "raw_sources",
            "compress": "compressed_transcripts",
            "analyze_domain": "domain_analysis",
            "prepare_calendar": "calendar",
            "prepare_weather": "weather",
            "prepare_spiritual": "spiritual",
            "prepare_local": "local_items",
            "seams": "seam_data",
            "cross_domain": "cross_domain_output",
            "assemble": "digest_json",
            "anomaly": "anomaly_report",
            "briefing_packet": "briefing_packet",
            "send": "send_result",
        }
        for stage, expected_key in mappings.items():
            assert _stage_artifact_key(stage) == expected_key, (
                f"Stage '{stage}' expected key '{expected_key}', got '{_stage_artifact_key(stage)}'"
            )

    def test_unknown_stage_returns_identity(self):
        assert _stage_artifact_key("unknown_stage") == "unknown_stage"


class TestEmptyStageOutput:
    def test_non_critical_stages_return_non_empty(self):
        for stage in _NON_CRITICAL_STAGES:
            output = _empty_stage_output(stage)
            assert output != {}, f"_empty_stage_output('{stage}') returned empty dict"

    def test_compress_returns_list(self):
        output = _empty_stage_output("compress")
        assert "compressed_transcripts" in output
        assert isinstance(output["compressed_transcripts"], list)

    def test_seams_returns_structure(self):
        output = _empty_stage_output("seams")
        assert "seam_data" in output
        assert "contested_narratives" in output["seam_data"]
        assert "coverage_gaps" in output["seam_data"]

    def test_prepare_weather_returns_empty_dicts(self):
        output = _empty_stage_output("prepare_weather")
        assert "weather" in output
        assert "weather_html" in output

    def test_prepare_spiritual_returns_empty_dict(self):
        output = _empty_stage_output("prepare_spiritual")
        assert "spiritual" in output

    def test_prepare_local_returns_empty_list(self):
        output = _empty_stage_output("prepare_local")
        assert "local_items" in output
        assert isinstance(output["local_items"], list)

    def test_anomaly_returns_report_structure(self):
        output = _empty_stage_output("anomaly")
        assert "anomaly_report" in output
        assert "anomalies" in output["anomaly_report"]

    def test_briefing_packet_returns_empty_dict(self):
        output = _empty_stage_output("briefing_packet")
        assert "briefing_packet" in output

    def test_unknown_stage_returns_empty_dict(self):
        output = _empty_stage_output("nonexistent_stage")
        assert output == {}


class TestArtifactPersistence:
    def test_save_and_load_artifact(self, tmp_path):
        artifact_dir = tmp_path / "artifacts" / "test-artifact"
        artifact_dir.mkdir(parents=True)
        data = {"key": "value", "nested": {"a": 1}}
        _save_artifact(artifact_dir, "test", data)
        loaded = _load_artifact(artifact_dir, "test")
        assert loaded == data

    def test_load_nonexistent_artifact_returns_none(self, tmp_path):
        artifact_dir = tmp_path / "artifacts" / "2026-01-01"
        artifact_dir.mkdir(parents=True)
        assert _load_artifact(artifact_dir, "nonexistent") is None


class TestPruneArtifacts:
    def test_prunes_old_directories(self, tmp_path):
        artifacts_base = tmp_path / "output" / "artifacts"
        artifacts_base.mkdir(parents=True)

        # Create a directory with an old date
        old_dir = artifacts_base / "2020-01-01"
        old_dir.mkdir()
        (old_dir / "test.json").write_text("{}")

        # Create a recent directory
        recent_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        recent_dir = artifacts_base / recent_date
        recent_dir.mkdir()

        with patch("pipeline._ARTIFACTS_BASE", artifacts_base):
            _prune_artifacts(keep_days=30)

        assert not old_dir.exists()
        assert recent_dir.exists()

    def test_prunes_old_html_files(self, tmp_path):
        output_dir = tmp_path / "output"
        output_dir.mkdir(parents=True)

        artifacts_base = tmp_path / "artifacts"
        artifacts_base.mkdir(parents=True)

        # Create an old HTML file
        old_html = output_dir / "2020-01-01.html"
        old_html.write_text("<html></html>")
        # Set mtime to 60 days ago
        old_time = (datetime.now() - timedelta(days=60)).timestamp()
        os.utime(old_html, (old_time, old_time))

        import pipeline as pipeline_mod

        with patch.object(pipeline_mod, "_OUTPUT_DIR", output_dir):
            with patch.object(pipeline_mod, "_ARTIFACTS_BASE", artifacts_base):
                _prune_artifacts(keep_days=30)

        assert not old_html.exists()
