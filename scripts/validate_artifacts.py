#!/usr/bin/env python3
"""Validate saved pipeline artifacts against stage contracts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from morning_digest.contracts import (
    normalize_cross_domain_output_artifact,
    normalize_cross_domain_plan_artifact,
    normalize_domain_analysis,
    normalize_seam_annotations_artifact,
    normalize_seam_candidates_artifact,
)


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _domain_analysis_path(path: Path) -> Path:
    if path.is_dir():
        return path / "domain_analysis.json"
    return path


def validate_domain_analysis(path: Path) -> list[dict]:
    artifact_path = _domain_analysis_path(path)
    if not artifact_path.exists():
        return [
            {
                "path": str(artifact_path),
                "message": "domain_analysis artifact not found",
            }
        ]
    _, issues = normalize_domain_analysis(_load_json(artifact_path))
    return issues


def validate_optional_seam_artifacts(path: Path, domain_analysis: dict) -> list[dict]:
    if not path.is_dir():
        return []

    issues: list[dict] = []
    candidates_path = path / "seam_candidates.json"
    if candidates_path.exists():
        _, candidate_issues = normalize_seam_candidates_artifact(
            _load_json(candidates_path), domain_analysis
        )
        issues.extend({"artifact": "seam_candidates", **issue} for issue in candidate_issues)

    annotations_path = path / "seam_annotations.json"
    if annotations_path.exists():
        _, annotation_issues = normalize_seam_annotations_artifact(
            _load_json(annotations_path), domain_analysis
        )
        issues.extend(
            {"artifact": "seam_annotations", **issue}
            for issue in annotation_issues
        )

    return issues


def validate_optional_cross_domain_artifacts(path: Path) -> list[dict]:
    if not path.is_dir():
        return []

    issues: list[dict] = []
    plan_path = path / "cross_domain_plan.json"
    if plan_path.exists():
        _, plan_issues = normalize_cross_domain_plan_artifact(_load_json(plan_path))
        issues.extend({"artifact": "cross_domain_plan", **issue} for issue in plan_issues)

    output_path = path / "cross_domain_output.json"
    if output_path.exists():
        _, output_issues = normalize_cross_domain_output_artifact(
            _load_json(output_path)
        )
        issues.extend(
            {"artifact": "cross_domain_output", **issue} for issue in output_issues
        )

    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate saved Morning Digest pipeline artifacts."
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Artifact date directory or a domain_analysis.json file",
    )
    args = parser.parse_args(argv)

    domain_analysis_path = _domain_analysis_path(args.path)
    domain_analysis = {}
    issues = validate_domain_analysis(args.path)
    if domain_analysis_path.exists():
        domain_analysis, _domain_issues = normalize_domain_analysis(
            _load_json(domain_analysis_path)
        )
        issues.extend(validate_optional_seam_artifacts(args.path, domain_analysis))
        issues.extend(validate_optional_cross_domain_artifacts(args.path))
    if not issues:
        print("artifacts: OK")
        return 0

    print("artifacts: contract issues found")
    for issue in issues:
        artifact = issue.get("artifact")
        prefix = f"{artifact}: " if artifact else ""
        print(f"- {prefix}{issue['path']}: {issue['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
