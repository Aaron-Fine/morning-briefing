"""Tests for scripts/validate_artifacts.py."""

import json

from scripts.validate_artifacts import validate_domain_analysis
from scripts.validate_artifacts import validate_optional_seam_artifacts


def test_validate_domain_analysis_reports_shape_issue(tmp_path):
    artifact_path = tmp_path / "domain_analysis.json"
    artifact_path.write_text(json.dumps({"ai_tech": {"items": "bad"}}))

    issues = validate_domain_analysis(tmp_path)

    assert issues == [
        {
            "path": "domain_analysis.ai_tech.items",
            "message": "items is not a list",
        }
    ]


def test_validate_optional_seam_artifacts_reports_shape_issue(tmp_path):
    (tmp_path / "seam_candidates.json").write_text(
        json.dumps({"candidates": [{"item_id": "item-1", "possible_evidence": "bad"}]})
    )
    domain_analysis = {"ai_tech": {"items": [{"item_id": "item-1"}]}}

    issues = validate_optional_seam_artifacts(tmp_path, domain_analysis)

    assert issues == [
        {
            "artifact": "seam_candidates",
            "path": "seam_candidates.candidates[0].possible_evidence",
            "message": "possible_evidence is not a list",
        }
    ]
