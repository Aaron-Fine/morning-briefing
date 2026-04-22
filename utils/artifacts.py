"""Shared helpers for dated pipeline artifact directories."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def artifact_dir(base: Path, run_date: str) -> Path:
    """Return and create the artifact directory for a run date."""
    path = base / run_date
    path.mkdir(parents=True, exist_ok=True)
    return path


def iter_recent_dirs(base: Path, limit: int | None = None) -> list[Path]:
    """Return dated artifact directories newest first."""
    if not base.exists():
        return []
    dirs = sorted(
        [d for d in base.iterdir() if d.is_dir() and len(d.name) == 10],
        reverse=True,
    )
    return dirs[:limit] if limit is not None else dirs


def find_most_recent_dir(base: Path, before_date: str | None = None) -> Path | None:
    """Find the newest dated artifact directory, optionally before a date."""
    for path in iter_recent_dirs(base):
        if before_date and path.name >= before_date:
            continue
        return path
    return None


def save_artifact(artifact_dir_path: Path, name: str, data: Any) -> None:
    """Save a stage output value as a JSON file."""
    path = artifact_dir_path / f"{name}.json"
    try:
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception as exc:
        log.warning(f"Failed to save artifact {name}.json: {exc}")


def load_artifact(artifact_dir_path: Path, name: str) -> Any:
    """Load a previously saved artifact. Returns None if not found/readable."""
    path = artifact_dir_path / f"{name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning(f"Failed to load artifact {name}.json: {exc}")
        return None
