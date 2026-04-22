"""Configuration loading helpers."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml

CONFIG_PARTS = ("pipeline.yaml", "sources.yaml", "delivery.yaml")


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge dictionaries without mutating inputs."""
    merged = deepcopy(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a mapping: {path}")
    return data


def load_config(root: Path | None = None) -> dict:
    """Load split config files, with legacy config.yaml as an optional override."""
    root = root or Path(__file__).resolve().parent.parent
    config_dir = root / "config"

    merged: dict = {}
    if config_dir.exists():
        for name in CONFIG_PARTS:
            merged = _deep_merge(merged, _load_yaml(config_dir / name))

    legacy_path = root / "config.yaml"
    legacy = _load_yaml(legacy_path)
    if legacy and not legacy.get("_split_config"):
        merged = _deep_merge(merged, legacy)

    if not merged:
        raise FileNotFoundError(
            f"No configuration found in {config_dir} or {legacy_path}"
        )
    return merged
