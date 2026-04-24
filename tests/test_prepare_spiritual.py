"""Tests for stages/prepare_spiritual.py — deterministic daily rendering."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.prepare_spiritual import run


class TestPrepareSpiritualRun:
    @pytest.fixture(autouse=True)
    def no_weekly_artifact(self, monkeypatch):
        monkeypatch.setattr(
            "stages.prepare_spiritual._find_latest_weekly_artifact",
            lambda today=None: None,
        )
        monkeypatch.setattr(
            "stages.prepare_spiritual._load_weekly_artifact",
            lambda week_start: None,
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
            "week_start": "2026-01-05",
        }

    def _make_context(self, cfm_data=None):
        if cfm_data is None:
            cfm_data = self._make_cfm_data()
        return {"raw_sources": {"come_follow_me": cfm_data}}

    def test_no_weekly_artifact_returns_empty_reflection(self, caplog):
        with caplog.at_level("WARNING"):
            result = run(self._make_context(), {})
        assert "no weekly artifact found" in caplog.text
        assert result["spiritual"]["reflection"] == ""

    def test_missing_cfm_data_returns_empty(self, caplog):
        context = {"raw_sources": {}}
        with caplog.at_level("WARNING"):
            result = run(context, {})
        assert result["spiritual"] == {}
        assert "no Come Follow Me data" in caplog.text

    def test_cfm_without_reading_returns_empty(self):
        context = {"raw_sources": {"come_follow_me": {"title": "No reading"}}}
        result = run(context, {})
        assert result["spiritual"] == {}

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

    def test_uses_exact_weekly_artifact_for_key_scripture(self, monkeypatch):
        weekly = {
            "week_start": "2026-01-05",
            "weekly_purpose": "Purpose",
            "daily_units": [
                {
                    "id": "focus-1",
                    "kind": "key_scripture",
                    "title": "Service reveals what covenant means",
                    "anchor_ref": "Mosiah 2:17",
                    "source_refs": ["Mosiah 2:17"],
                    "core_claim": "Benjamin ties devotion to service.",
                    "supporting_excerpt": (
                        "Service is not side work in the kingdom; "
                        "it is the form covenant life takes."
                    ),
                    "enhancement": (
                        "The verse is often quoted sentimentally, "
                        "but Benjamin is teaching obligation."
                    ),
                    "application": "Choose one person to serve without announcing it.",
                    "prompt_hint": "",
                }
            ],
            "proposed_sequence": {"monday": "focus-1"},
        }
        monkeypatch.setattr(
            "stages.prepare_spiritual._load_weekly_artifact",
            lambda week_start: weekly if week_start == "2026-01-05" else None,
        )
        monkeypatch.setattr(
            "stages.prepare_spiritual.now_local",
            lambda: __import__("datetime").datetime(2026, 1, 5),
        )

        result = run(self._make_context(), {})

        reflection = result["spiritual"]["reflection"]
        assert "Service is not side work in the kingdom" in reflection
        assert "Benjamin ties devotion to service." in reflection
        assert "Benjamin is teaching obligation." in reflection
        assert "Choose one person to serve without announcing it." in reflection
        # No canned scaffolds leak through
        assert "deserves slow reading" not in reflection
        assert result["spiritual"]["focus_id"] == "focus-1"
        assert result["spiritual"]["daily_unit_kind"] == "key_scripture"
        assert result["spiritual"]["text_ref"] == "Mosiah 2:17"

    def test_renders_misuse_correction_unit(self, monkeypatch):
        weekly = {
            "week_start": "2026-01-05",
            "daily_units": [
                {
                    "id": "focus-5",
                    "kind": "misuse_correction",
                    "title": "Service as public image management",
                    "anchor_ref": "",
                    "source_refs": [],
                    "core_claim": (
                        "Benjamin treats service as response to God, "
                        "not branding."
                    ),
                    "supporting_excerpt": (
                        "It is easy to use service language to talk about "
                        "ourselves instead of our obligations."
                    ),
                    "enhancement": "That kind of misuse turns the neighbor into a stage prop.",
                    "application": "Do one needed thing today that nobody will applaud.",
                    "prompt_hint": "",
                }
            ],
            "proposed_sequence": {"friday": "focus-5"},
        }
        monkeypatch.setattr(
            "stages.prepare_spiritual._load_weekly_artifact",
            lambda week_start: weekly,
        )
        monkeypatch.setattr(
            "stages.prepare_spiritual.now_local",
            lambda: __import__("datetime").datetime(2026, 1, 9),
        )

        result = run(self._make_context(), {})

        reflection = result["spiritual"]["reflection"]
        assert "use service language to talk about ourselves" in reflection
        assert "Benjamin treats service as response to God" in reflection
        assert "turns the neighbor into a stage prop." in reflection
        assert "Do one needed thing today that nobody will applaud." in reflection
        # No canned scaffolds leak through
        assert "easy to flatten into a slogan" not in reflection
        assert "better reading takes the text on its own terms" not in reflection

    def test_legacy_daily_foci_are_still_renderable(self, monkeypatch):
        weekly = {
            "week_start": "2026-01-05",
            "daily_foci": [
                {
                    "id": "focus-1",
                    "text_ref": "Mosiah 2:17",
                    "guide_excerpt": "Serving others is the visible shape of devotion.",
                }
            ],
            "proposed_sequence": {"monday": "focus-1"},
        }
        monkeypatch.setattr(
            "stages.prepare_spiritual._load_weekly_artifact",
            lambda week_start: weekly,
        )
        monkeypatch.setattr(
            "stages.prepare_spiritual.now_local",
            lambda: __import__("datetime").datetime(2026, 1, 5),
        )

        result = run(self._make_context(), {})

        # Legacy `daily_foci` surface the guide_excerpt as the reflection body.
        # The anchor_ref is exposed separately via text_ref, not inlined.
        assert result["spiritual"]["reflection"] == "Serving others is the visible shape of devotion."
        assert result["spiritual"]["text_ref"] == "Mosiah 2:17"
