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
        "daily_foci": [
            {
                "id": "focus-1",
                "text_ref": "Mosiah 2:17",
                "guide_excerpt": "Serve carefully",
            }
        ],
        "misuses": [],
        "applications": [],
        "conspicuous_absences": [],
        "proposed_sequence": {"monday": "focus-1"},
    }

    with patch("stages.prepare_spiritual_weekly._GUIDE_DIR", guide_dir):
        with patch("stages.prepare_spiritual_weekly._ARTIFACT_DIR", artifact_dir):
            result = run(_context(), {}, model_config={"provider": "fireworks"})

    assert result["spiritual_weekly"]["daily_foci"][0]["id"] == "focus-1"
    written = json.loads(
        (artifact_dir / "2026-01-05_weekly.json").read_text(encoding="utf-8")
    )
    assert written["proposed_sequence"]["monday"] == "focus-1"


def test_missing_guide_writes_minimal_artifact(tmp_path):
    guide_dir = tmp_path / "guides"
    artifact_dir = tmp_path / "artifacts"
    guide_dir.mkdir()

    with patch("stages.prepare_spiritual_weekly._GUIDE_DIR", guide_dir):
        with patch("stages.prepare_spiritual_weekly._ARTIFACT_DIR", artifact_dir):
            result = run(_context(), {}, model_config={"provider": "fireworks"})

    assert result["spiritual_weekly"]["missing_guide"] is True
    assert (artifact_dir / "2026-01-05_weekly.json").exists()
