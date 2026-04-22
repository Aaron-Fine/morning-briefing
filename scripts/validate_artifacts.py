#!/usr/bin/env python3
"""Validate saved pipeline artifacts against stage contracts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from morning_digest.contracts import normalize_domain_analysis


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

    issues = validate_domain_analysis(args.path)
    if not issues:
        print("domain_analysis: OK")
        return 0

    print("domain_analysis: contract issues found")
    for issue in issues:
        print(f"- {issue['path']}: {issue['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
