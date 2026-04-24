"""Tests for stages/prepare_spiritual_weekly.py."""

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.prepare_spiritual_weekly import run


def _context():
    return {
        "raw_sources": {
            "come_follow_me": {
                "reading": "Mosiah 1-3",
                "title": "King Benjamin",
                "week_start": "2026-01-05",
            }
        }
    }


@patch("stages.prepare_spiritual_weekly.call_llm")
def test_generates_weekly_artifact(mock_llm, tmp_path):
    guide_dir = tmp_path / "guides"
    artifact_dir = tmp_path / "artifacts"
    guide_dir.mkdir()
    (guide_dir / "2026-01-05.md").write_text("# Purpose\nServe carefully", encoding="utf-8")
    mock_llm.return_value = {
        "week_start": "2026-01-05",
        "cfm_range": "Mosiah 1-3",
        "weekly_purpose": "Serve carefully",
        "daily_units": [
            {
                "id": "focus-1",
                "kind": "key_scripture",
                "title": "Service is how covenant loyalty becomes visible",
                "anchor_ref": "Mosiah 2:17",
                "source_refs": ["Mosiah 2:17"],
                "core_claim": "Service is covenantal, not performative.",
                "supporting_excerpt": "Serve carefully",
                "enhancement": "King Benjamin turns status upside down.",
                "application": "Look for one quiet act of service today.",
                "prompt_hint": "Direct and warm.",
            }
        ],
        "misuses": [
            {
                "text": "Service as public image management",
                "common_use": "Serving to be seen as righteous.",
                "correction": "Benjamin treats service as response to God, not branding.",
                "cost_bearer": "The people being used as props.",
            }
        ],
        "applications": [],
        "conspicuous_absences": [],
        "proposed_sequence": {"monday": "focus-1"},
    }

    with patch("stages.prepare_spiritual_weekly._GUIDE_DIR", guide_dir):
        with patch("stages.prepare_spiritual_weekly._ARTIFACT_DIR", artifact_dir):
            result = run(_context(), {}, model_config={"provider": "fireworks"})

    assert result["spiritual_weekly"]["daily_units"][0]["kind"] == "key_scripture"
    assert result["spiritual_weekly"]["daily_foci"][0]["id"] == "focus-1"
    written = json.loads(
        (artifact_dir / "2026-01-05_weekly.json").read_text(encoding="utf-8")
    )
    assert written["proposed_sequence"]["monday"] == "focus-1"
    assert any(
        unit["kind"] == "misuse_correction"
        for unit in written["daily_units"]
    )


@patch("stages.prepare_spiritual_weekly.call_llm")
def test_missing_guide_writes_minimal_artifact(mock_llm, tmp_path):
    guide_dir = tmp_path / "guides"
    artifact_dir = tmp_path / "artifacts"
    guide_dir.mkdir()
    mock_llm.side_effect = RuntimeError("guide generation failed")

    with patch("stages.prepare_spiritual_weekly._GUIDE_DIR", guide_dir):
        with patch("stages.prepare_spiritual_weekly._ARTIFACT_DIR", artifact_dir):
            result = run(_context(), {}, model_config={"provider": "fireworks"})

    assert result["spiritual_weekly"]["missing_guide"] is True
    assert (artifact_dir / "2026-01-05_weekly.json").exists()


@patch("stages.prepare_spiritual_weekly.call_llm")
def test_missing_guide_auto_generates_then_builds_artifact(mock_llm, tmp_path):
    guide_dir = tmp_path / "guides"
    artifact_dir = tmp_path / "artifacts"
    guide_dir.mkdir()
    mock_llm.side_effect = [
        "# Lesson Overview\nGenerated guide",
        {
            "week_start": "2026-01-05",
            "cfm_range": "Mosiah 1-3",
            "weekly_purpose": "Generated purpose",
            "daily_units": [
                {
                    "id": "focus-1",
                    "kind": "narrative_unit",
                    "title": "Benjamin gathers the people to remember the covenant",
                    "anchor_ref": "Mosiah 2:1-9",
                    "source_refs": ["Mosiah 2:1-9"],
                    "core_claim": "Covenant memory has to be rehearsed in public.",
                    "supporting_excerpt": "Generated guide",
                    "enhancement": "",
                    "application": "Notice what helps you remember your covenants.",
                    "prompt_hint": "",
                }
            ],
            "misuses": [],
            "applications": [],
            "conspicuous_absences": [],
            "proposed_sequence": {"monday": "focus-1"},
        },
    ]

    with patch("stages.prepare_spiritual_weekly._GUIDE_DIR", guide_dir):
        with patch("stages.prepare_spiritual_weekly._ARTIFACT_DIR", artifact_dir):
            result = run(_context(), {}, model_config={"provider": "fireworks"})

    assert (guide_dir / "2026-01-05.md").exists()
    assert result["spiritual_weekly"]["weekly_purpose"] == "Generated purpose"
    assert mock_llm.call_count == 2
