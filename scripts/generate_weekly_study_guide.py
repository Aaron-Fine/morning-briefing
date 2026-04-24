#!/usr/bin/env python3
"""Generate a weekly Come, Follow Me study guide markdown artifact."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from morning_digest.config import load_config
from sources.come_follow_me import get_lesson_for_date
from stages.prepare_spiritual_weekly import generate_weekly_guide
from utils.time import now_local


log = logging.getLogger("generate_weekly_study_guide")
_ROOT = Path(__file__).resolve().parent.parent


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the weekly markdown study guide used by the spiritual pipeline."
    )
    parser.add_argument(
        "--week-start",
        help="ISO date for the lesson week start (for example 2026-04-20).",
    )
    parser.add_argument(
        "--date",
        dest="target_date",
        help="ISO date within the lesson week. Defaults to today.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing weekly guide for that week.",
    )
    return parser.parse_args()


def _resolve_target_date(args: argparse.Namespace) -> date:
    if args.week_start:
        return date.fromisoformat(args.week_start)
    if args.target_date:
        return date.fromisoformat(args.target_date)
    return now_local().date()


def _resolve_model_config(config: dict) -> dict | None:
    resolved = dict(config.get("llm", {}))
    for stage_cfg in config.get("pipeline", {}).get("stages", []):
        if stage_cfg.get("name") == "prepare_spiritual_weekly":
            resolved.update(stage_cfg.get("model", {}))
            break
    return resolved or None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = _parse_args()
    config = load_config(_ROOT)
    lesson = get_lesson_for_date(config, _resolve_target_date(args))
    if not lesson.get("week_start") or not lesson.get("reading"):
        log.error("No Come, Follow Me lesson found for the requested date.")
        return 1

    model_config = _resolve_model_config(config)
    if not model_config:
        log.error("No model configuration found for prepare_spiritual_weekly.")
        return 1

    try:
        path = generate_weekly_guide(lesson, model_config, force=args.force)
    except Exception as exc:
        log.error(f"Guide generation failed: {exc}")
        return 1

    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
