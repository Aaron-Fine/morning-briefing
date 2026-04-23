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
    _get_stage_meta,
    _stage_artifact_key,
    _empty_stage_output,
    _NON_CRITICAL_STAGES,
    _load_cached_stage_outputs,
    _run_stage_after_hook,
    _prepare_cross_domain_context,
    _log_stage_observability,
    _save_artifact,
    _load_artifact,
    _prune_artifacts,
    run_pipeline,
)


class TestStageMetadata:
    def test_prepare_weather_loads_all_context_keys(self):
        meta = _get_stage_meta("prepare_weather")
        assert meta["artifact_key"] == "weather"
        assert meta["context_keys"] == ["weather", "weather_html"]
        assert meta["non_critical"] is True

    def test_unknown_stage_gets_safe_defaults(self):
        meta = _get_stage_meta("unknown_stage")
        assert meta["artifact_key"] == "unknown_stage"
        assert meta["context_keys"] == ["unknown_stage"]
        assert meta["non_critical"] is False
        assert meta["empty_output"] is None

    def test_enrich_articles_uses_separate_source_artifact(self):
        meta = _get_stage_meta("enrich_articles")
        assert meta["artifact_key"] == "enrich_articles"
        assert meta["context_keys"] == ["enriched_sources", "enrich_articles"]
        assert "raw_sources" not in meta["context_keys"]


class TestStageObservability:
    def test_contract_issues_are_logged(self, caplog):
        with caplog.at_level("WARNING", logger="pipeline"):
            _log_stage_observability(
                "seams",
                {
                    "seam_contract_issues": [
                        {"path": "seam_candidates[0]", "message": "bad shape"}
                    ]
                },
            )

        assert "emitted 1 contract issue(s)" in caplog.text
        assert "seam_candidates[0]: bad shape" in caplog.text

    def test_anomaly_report_is_logged(self, caplog):
        with caplog.at_level("WARNING", logger="pipeline"):
            _log_stage_observability(
                "anomaly",
                {"anomaly_report": {"anomaly_count": 2, "checks_run": 5}},
            )

        assert "found 2 anomaly warning(s) across 5 checks" in caplog.text


class TestStageArtifactKey:
    def test_known_stages_return_explicit_keys(self):
        mappings = {
            "collect": "raw_sources",
            "enrich_articles": "enrich_articles",
            "compress": "compressed_transcripts",
            "analyze_domain": "domain_analysis",
            "prepare_calendar": "calendar",
            "prepare_weather": "weather",
            "prepare_spiritual_weekly": "spiritual_weekly",
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
        assert "seam_candidates" in output
        assert "candidates" in output["seam_candidates"]
        assert "seam_annotations" in output
        assert "per_item" in output["seam_annotations"]
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

    def test_prepare_spiritual_weekly_returns_empty_dict(self):
        output = _empty_stage_output("prepare_spiritual_weekly")
        assert "spiritual_weekly" in output

    def test_prepare_local_returns_empty_list(self):
        output = _empty_stage_output("prepare_local")
        assert "local_items" in output
        assert isinstance(output["local_items"], list)
        assert "regional_items" in output
        assert isinstance(output["regional_items"], list)

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

    def test_load_cached_stage_outputs_loads_secondary_artifacts(self, tmp_path):
        artifact_dir = tmp_path / "artifacts" / "2026-01-01"
        artifact_dir.mkdir(parents=True)
        _save_artifact(artifact_dir, "weather", {"forecast": []})
        _save_artifact(artifact_dir, "weather_html", "<p>Forecast</p>")

        context = {}
        _load_cached_stage_outputs("prepare_weather", context, artifact_dir)

        assert context["weather"] == {"forecast": []}
        assert context["weather_html"] == "<p>Forecast</p>"

    def test_load_cached_cross_domain_outputs_loads_plan_and_output(self, tmp_path):
        artifact_dir = tmp_path / "artifacts" / "2026-01-01"
        artifact_dir.mkdir(parents=True)
        _save_artifact(artifact_dir, "cross_domain_plan", {"schema_version": 1})
        _save_artifact(artifact_dir, "cross_domain_output", {"at_a_glance": []})

        context = {}
        _load_cached_stage_outputs("cross_domain", context, artifact_dir)

        assert context["cross_domain_plan"] == {"schema_version": 1}
        assert context["cross_domain_output"] == {"at_a_glance": []}

    def test_load_cached_enrich_articles_promotes_enriched_sources(self, tmp_path):
        artifact_dir = tmp_path / "artifacts" / "2026-01-01"
        artifact_dir.mkdir(parents=True)
        original = {"rss": [{"url": "https://x/1", "summary": "raw"}]}
        enriched = {"rss": [{"url": "https://x/1", "summary": "enriched"}]}
        _save_artifact(artifact_dir, "enriched_sources", enriched)
        _save_artifact(artifact_dir, "enrich_articles", {"records": [{"status": "ok"}]})

        context = {"raw_sources": original}
        _load_cached_stage_outputs("enrich_articles", context, artifact_dir)

        assert context["enriched_sources"] == enriched
        assert context["raw_sources"] == enriched
        assert context["enrich_articles"] == {"records": [{"status": "ok"}]}

    def test_enrich_articles_after_hook_promotes_runtime_sources(self):
        context = {"raw_sources": {"rss": [{"summary": "raw"}]}}
        outputs = {
            "enriched_sources": {"rss": [{"summary": "enriched"}]},
            "enrich_articles": {"records": []},
        }

        _run_stage_after_hook("enrich_articles", context, outputs)

        assert context["raw_sources"] == {"rss": [{"summary": "enriched"}]}

    def test_enrich_articles_after_hook_preserves_raw_sources_on_failure(self):
        context = {"raw_sources": {"rss": [{"summary": "raw"}]}}
        outputs = {"enrich_articles": {"records": []}}

        _run_stage_after_hook("enrich_articles", context, outputs)

        assert context["raw_sources"] == {"rss": [{"summary": "raw"}]}

    def test_load_cached_assemble_outputs_restores_html(self, tmp_path):
        artifact_dir = tmp_path / "artifacts" / "2026-01-01"
        artifact_dir.mkdir(parents=True)
        _save_artifact(artifact_dir, "template_data", {"date": "Apr 18"})
        _save_artifact(artifact_dir, "digest_json", {"date": "Apr 18"})
        (artifact_dir / "digest.html").write_text("<html>digest</html>", encoding="utf-8")

        context = {}
        _load_cached_stage_outputs("assemble", context, artifact_dir)

        assert context["template_data"] == {"date": "Apr 18"}
        assert context["digest_json"] == {"date": "Apr 18"}
        assert context["html"] == "<html>digest</html>"

    def test_prepare_cross_domain_context_loads_same_day_plan_for_from_plan(self, tmp_path):
        artifact_dir = tmp_path / "artifacts" / "2026-01-01"
        artifact_dir.mkdir(parents=True)
        _save_artifact(artifact_dir, "cross_domain_plan", {"schema_version": 1})

        context = {}
        _prepare_cross_domain_context(
            context,
            artifact_dir=artifact_dir,
            stage_from="cross_domain",
            from_plan=True,
            run_date="2026-01-01",
        )

        assert context["cross_domain_plan"] == {"schema_version": 1}
        assert context["cross_domain_from_plan"] is True

    def test_prepare_cross_domain_context_missing_same_day_plan_does_not_set_flag(self, tmp_path):
        artifact_dir = tmp_path / "artifacts" / "2026-01-01"
        artifact_dir.mkdir(parents=True)

        context = {}
        _prepare_cross_domain_context(
            context,
            artifact_dir=artifact_dir,
            stage_from="cross_domain",
            from_plan=True,
            run_date="2026-01-01",
        )

        assert "cross_domain_plan" not in context
        assert "cross_domain_from_plan" not in context


class TestRunPipeline:
    def test_run_meta_is_available_to_briefing_packet_stage(self, tmp_path):
        captured = {}

        class CollectModule:
            @staticmethod
            def run(context, config, model_config, **kwargs):
                return {"raw_sources": {"rss": []}}

        class BriefingPacketModule:
            @staticmethod
            def run(context, config, model_config, **kwargs):
                captured["run_meta"] = context.get("run_meta")
                return {"briefing_packet": {"metadata": context.get("run_meta", {})}}

        def load_stage(name):
            return {
                "collect": CollectModule,
                "briefing_packet": BriefingPacketModule,
            }[name]

        config = {
            "pipeline": {
                "stages": [
                    {"name": "collect"},
                    {"name": "briefing_packet"},
                ]
            }
        }

        with (
            patch("pipeline._setup_logging"),
            patch("pipeline.load_config", return_value=config),
            patch("pipeline._artifact_dir", return_value=tmp_path),
            patch("pipeline._prune_artifacts"),
            patch("pipeline._load_stage_module", side_effect=load_stage),
        ):
            run_pipeline(dry_run=True)

        assert captured["run_meta"]["options"]["dry_run"] is True
        assert "collect" in captured["run_meta"]["stage_timings"]
        assert captured["run_meta"]["stage_failures"] == []


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
