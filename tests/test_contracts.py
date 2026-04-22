"""Cross-module contract tests.

These tests verify that constants, schemas, and field names are consistent
across modules — catching the kinds of drift that caused bugs #1–#3.
"""

import sys
import os
import re
from datetime import datetime
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from morning_digest.validate import VALID_TAGS, VALID_TAG_LABELS
from stages.cross_domain import _VALID_TAGS, _TAG_LABELS, _SYSTEM_PROMPT
from stages.assemble import _TAG_LABELS as ASSEMBLE_TAG_LABELS
from stages.prepare_calendar import _parse_date
from stages.prepare_local import CONSUMED_RSS_CATEGORIES
from templates.email_template import EMAIL_TEMPLATE


def _configured_stage_names() -> list[str]:
    config_path = Path(__file__).parent.parent / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return [
        stage["name"]
        for stage in config.get("pipeline", {}).get("stages", [])
        if stage.get("name")
    ]


class TestTagVocabularyConsistency:
    """Tag vocabulary must be identical across validate, cross_domain, assemble, and CSS."""

    def test_validate_tags_match_cross_domain_tags(self):
        assert VALID_TAGS == _VALID_TAGS, (
            f"validate.VALID_TAGS != cross_domain._VALID_TAGS. "
            f"Missing from cross_domain: {VALID_TAGS - _VALID_TAGS}, "
            f"Extra in cross_domain: {_VALID_TAGS - VALID_TAGS}"
        )

    def test_cross_domain_labels_cover_all_tags(self):
        for tag in _VALID_TAGS:
            assert tag in _TAG_LABELS, (
                f"Tag '{tag}' missing from cross_domain._TAG_LABELS"
            )

    def test_assemble_labels_cover_all_tags(self):
        for tag in VALID_TAGS:
            assert tag in ASSEMBLE_TAG_LABELS, (
                f"Tag '{tag}' missing from assemble._TAG_LABELS"
            )

    def test_cross_domain_and_assemble_labels_match(self):
        assert _TAG_LABELS == ASSEMBLE_TAG_LABELS, (
            f"cross_domain._TAG_LABELS != assemble._TAG_LABELS. "
            f"Differences: {_TAG_LABELS.keys() ^ ASSEMBLE_TAG_LABELS.keys()}"
        )

    def test_css_tag_variables_match_valid_tags(self):
        template_path = Path(__file__).parent.parent / "templates" / "email_template.py"
        css = template_path.read_text()
        css_tags = set(re.findall(r"--tag-(\w+)-text:", css))
        assert css_tags == VALID_TAGS, (
            f"CSS tag variables != validate.VALID_TAGS. "
            f"Missing from CSS: {VALID_TAGS - css_tags}, "
            f"Extra in CSS: {css_tags - VALID_TAGS}"
        )


class TestTagLabelConsistency:
    """validate.VALID_TAG_LABELS must match cross_domain._TAG_LABELS."""

    def test_validate_labels_match_cross_domain_labels(self):
        assert VALID_TAG_LABELS == _TAG_LABELS, (
            f"validate.VALID_TAG_LABELS != cross_domain._TAG_LABELS. "
            f"Missing: {_TAG_LABELS.keys() - VALID_TAG_LABELS.keys()}, "
            f"Extra: {VALID_TAG_LABELS.keys() - _TAG_LABELS.keys()}"
        )

    def test_validate_label_values_match(self):
        cross_domain_label_values = set(_TAG_LABELS.values())
        validate_label_values = set(VALID_TAG_LABELS.values())
        assert validate_label_values == cross_domain_label_values, (
            f"validate.VALID_TAG_LABELS values != cross_domain._TAG_LABELS values. "
            f"Missing: {cross_domain_label_values - validate_label_values}, "
            f"Extra: {validate_label_values - cross_domain_label_values}"
        )


class TestLaunchDateFormatRoundTrip:
    """Launch date format from sources/launches.py must be parseable by prepare_calendar."""

    def test_parse_date_with_z_suffix(self):
        test_input = "2026-04-15 14:30Z"
        expected = (2026, 4, 15, 14, 30)  # year, month, day, hour, minute
        dt = _parse_date(test_input)
        assert dt != datetime.max, (
            f"_parse_date returned datetime.max for '{test_input}'"
        )
        assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == expected

    def test_parse_date_without_z_suffix(self):
        test_input = "2026-04-15 14:30"
        expected = (2026, 4, 15, 14, 30)
        dt = _parse_date(test_input)
        assert dt != datetime.max, (
            f"_parse_date returned datetime.max for '{test_input}'"
        )
        assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == expected

    def test_parse_date_iso_format_still_works(self):
        test_input = "2026-04-15T14:30:00Z"
        dt = _parse_date(test_input)
        assert dt != datetime.max
        # Extract year from input to avoid hardcoding in assertion
        expected_year = int(test_input.split("-")[0])
        assert dt.year == expected_year

    def test_parse_date_empty_string_returns_max(self):
        assert _parse_date("") == datetime.max

    def test_parse_date_none_returns_max(self):
        assert _parse_date(None) == datetime.max


class TestDeepDiveFieldContract:
    """Every field referenced in the template for deep_dives must appear in the prompt schema."""

    def test_why_it_matters_in_prompt_schema(self):
        assert "why_it_matters" in _SYSTEM_PROMPT, (
            "why_it_matters field missing from cross_domain._SYSTEM_PROMPT deep_dives schema"
        )

    def test_deep_dive_template_fields_in_prompt(self):
        template_path = Path(__file__).parent.parent / "templates" / "email_template.py"
        template_source = template_path.read_text()
        dive_fields = set(re.findall(r"dive\.(\w+)", template_source))
        for field in dive_fields:
            assert field in _SYSTEM_PROMPT, (
                f"Template references 'dive.{field}' but it is not in the prompt schema"
            )


class TestEmptyStageOutputCoverage:
    """Every non-critical stage must return a non-empty dict from _empty_stage_output."""

    def test_non_critical_stages_have_empty_output(self):
        from pipeline import _NON_CRITICAL_STAGES, _empty_stage_output

        for stage in _NON_CRITICAL_STAGES:
            output = _empty_stage_output(stage)
            assert output != {}, (
                f"_empty_stage_output('{stage}') returns {{}} — "
                f"downstream stages may crash on missing keys"
            )


class TestStageArtifactKeyCoverage:
    """Every stage in the pipeline manifest must map to an explicit artifact key."""

    def test_all_stages_have_explicit_keys(self):
        from pipeline import _STAGE_METADATA
        from pipeline import _stage_artifact_key

        stage_names = _configured_stage_names()

        for stage in stage_names:
            assert "artifact_key" in _STAGE_METADATA.get(stage, {}), (
                f"Stage '{stage}' has no explicit artifact_key metadata"
            )
            key = _stage_artifact_key(stage)
            assert key == _STAGE_METADATA[stage]["artifact_key"], (
                f"Stage '{stage}' artifact key does not match metadata"
            )


class TestStageMetadataCoverage:
    """Stage metadata should remain the single source of truth for pipeline behavior."""

    def test_known_stages_have_metadata_entries(self):
        from pipeline import _STAGE_METADATA

        stage_names = _configured_stage_names()

        for stage in stage_names:
            assert stage in _STAGE_METADATA, f"Missing stage metadata for '{stage}'"


class TestRssCategoryRoutingContract:
    """Every configured RSS category must be consumed by a desk or explicit stage."""

    def test_all_configured_rss_categories_have_active_consumers(self):
        from stages.analyze_domain import _resolve_domain_configs

        config_path = Path(__file__).parent.parent / "config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        rss_categories = {
            feed.get("category")
            for feed in config.get("rss", {}).get("feeds", [])
            if feed.get("category")
        }
        desk_categories = {
            category
            for desk in _resolve_domain_configs(config).values()
            for category in desk.get("categories", set())
        }
        consumed = desk_categories | CONSUMED_RSS_CATEGORIES

        assert rss_categories <= consumed, (
            "Configured RSS categories without an active consumer: "
            f"{sorted(rss_categories - consumed)}"
        )
