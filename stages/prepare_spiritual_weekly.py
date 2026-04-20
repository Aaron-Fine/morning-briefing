"""Stage: prepare_spiritual_weekly — build a durable weekly study artifact.

Runs once per Come Follow Me week. The stage reads the user-authored guide at
state/spiritual/weekly/{week_start}.md and writes:

  output/artifacts/spiritual/{week_start}_weekly.json

If the guide is missing, it writes a minimal artifact so the daily stage can
fall back cleanly.
"""

import json
import logging
from pathlib import Path

from morning_digest.llm import call_llm
from sources.come_follow_me import get_lesson_for_date
from utils.prompts import load_prompt
from utils.time import now_local

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_GUIDE_DIR = _ROOT / "state" / "spiritual" / "weekly"
_ARTIFACT_DIR = _ROOT / "output" / "artifacts" / "spiritual"
_SYSTEM_PROMPT = load_prompt("prepare_spiritual_weekly.md")
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday")


def _current_lesson(context: dict, config: dict) -> dict:
    cfm = context.get("raw_sources", {}).get("come_follow_me", {})
    if cfm.get("week_start"):
        return cfm
    return get_lesson_for_date(config, now_local().date())


def _artifact_path(week_start: str) -> Path:
    return _ARTIFACT_DIR / f"{week_start}_weekly.json"


def _minimal_artifact(lesson: dict, reason: str) -> dict:
    return {
        "week_start": lesson.get("week_start", ""),
        "cfm_range": lesson.get("reading", ""),
        "weekly_purpose": "",
        "daily_foci": [],
        "misuses": [],
        "applications": [],
        "conspicuous_absences": [],
        "proposed_sequence": {},
        "missing_guide": True,
        "fallback_reason": reason,
    }


def _load_existing(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning(f"prepare_spiritual_weekly: failed to read existing artifact: {exc}")
        return None


def _write_artifact(path: Path, artifact: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, default=str), encoding="utf-8")


def _validate_artifact(result: dict | None, lesson: dict) -> dict:
    if not isinstance(result, dict):
        result = {}

    daily_foci = []
    seen_ids: set[str] = set()
    for idx, focus in enumerate(result.get("daily_foci", []) or [], start=1):
        if not isinstance(focus, dict):
            continue
        focus_id = str(focus.get("id") or f"focus-{idx}").strip()
        if not focus_id or focus_id in seen_ids:
            focus_id = f"focus-{idx}"
        seen_ids.add(focus_id)
        daily_foci.append(
            {
                "id": focus_id,
                "text_ref": str(focus.get("text_ref", "")).strip(),
                "guide_excerpt": str(focus.get("guide_excerpt", "")).strip(),
            }
        )

    valid_ids = {focus["id"] for focus in daily_foci}
    proposed_sequence = {}
    raw_sequence = result.get("proposed_sequence", {}) or {}
    if isinstance(raw_sequence, dict):
        for day in _DAYS:
            focus_id = str(raw_sequence.get(day, "")).strip()
            if focus_id in valid_ids:
                proposed_sequence[day] = focus_id

    if daily_foci and not proposed_sequence:
        for day, focus in zip(_DAYS, daily_foci, strict=False):
            proposed_sequence[day] = focus["id"]

    return {
        "week_start": lesson.get("week_start", ""),
        "cfm_range": str(result.get("cfm_range") or lesson.get("reading", "")),
        "weekly_purpose": str(result.get("weekly_purpose", "")).strip(),
        "daily_foci": daily_foci,
        "misuses": [
            {
                "text": str(item.get("text", "")).strip(),
                "common_use": str(item.get("common_use", "")).strip(),
                "correction": str(item.get("correction", "")).strip(),
                "cost_bearer": str(item.get("cost_bearer", "")).strip(),
            }
            for item in (result.get("misuses", []) or [])
            if isinstance(item, dict)
        ],
        "applications": [
            {
                "question_or_insight": str(
                    item.get("question_or_insight", "")
                ).strip(),
                "grounding": str(item.get("grounding", "")).strip(),
            }
            for item in (result.get("applications", []) or [])
            if isinstance(item, dict)
        ],
        "conspicuous_absences": [
            str(item).strip()
            for item in (result.get("conspicuous_absences", []) or [])
            if str(item).strip()
        ],
        "proposed_sequence": proposed_sequence,
    }


def run(
    context: dict, config: dict, model_config: dict | None = None, **kwargs
) -> dict:
    lesson = _current_lesson(context, config)
    week_start = lesson.get("week_start", "")
    if not week_start:
        log.warning("prepare_spiritual_weekly: no CFM week_start available")
        return {"spiritual_weekly": {}}

    path = _artifact_path(week_start)
    existing = _load_existing(path)
    if existing is not None:
        log.info(f"prepare_spiritual_weekly: using existing artifact {path.name}")
        return {"spiritual_weekly": existing}

    guide_path = _GUIDE_DIR / f"{week_start}.md"
    if not guide_path.exists():
        artifact = _minimal_artifact(lesson, f"missing guide: {guide_path}")
        _write_artifact(path, artifact)
        log.warning(f"prepare_spiritual_weekly: missing guide {guide_path}")
        return {"spiritual_weekly": artifact}

    guide = guide_path.read_text(encoding="utf-8")
    if not model_config:
        artifact = _minimal_artifact(lesson, "no model_config")
        _write_artifact(path, artifact)
        log.warning("prepare_spiritual_weekly: no model config; wrote fallback artifact")
        return {"spiritual_weekly": artifact}

    user_content = f"""Week start: {week_start}
CFM range: {lesson.get('reading', '')}
Lesson title: {lesson.get('title', '')}

USER STUDY GUIDE:
{guide}

Return the weekly spiritual artifact as JSON."""

    try:
        raw = call_llm(
            _SYSTEM_PROMPT,
            user_content,
            model_config,
            max_retries=1,
            json_mode=True,
            stream=True,
        )
        artifact = _validate_artifact(raw, lesson)
    except Exception as exc:
        log.warning(f"prepare_spiritual_weekly: LLM call failed: {exc}")
        artifact = _minimal_artifact(lesson, f"llm failed: {exc}")

    _write_artifact(path, artifact)
    return {"spiritual_weekly": artifact}
