"""Stage: prepare_spiritual_weekly — build a durable weekly study artifact.

Runs once per Come Follow Me week. The stage reads the user-authored guide at
state/spiritual/weekly/{week_start}.md and writes:

  output/artifacts/spiritual/{week_start}_weekly.json

If the guide is missing, it first tries to generate the markdown guide from
Come, Follow Me lesson metadata. If guide generation fails, it writes a minimal
artifact so the daily stage can fall back cleanly.
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
_GUIDE_SYSTEM_PROMPT = load_prompt("generate_spiritual_weekly_guide.md")
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday")
_VALID_DAILY_UNIT_KINDS = {
    "narrative_unit",
    "key_scripture",
    "misuse_correction",
    "scholarly_insight",
    "language_context",
    "faithful_application",
}


def _current_lesson(context: dict, config: dict) -> dict:
    cfm = context.get("raw_sources", {}).get("come_follow_me", {})
    if cfm.get("week_start"):
        return cfm
    return get_lesson_for_date(config, now_local().date())


def _artifact_path(week_start: str) -> Path:
    return _ARTIFACT_DIR / f"{week_start}_weekly.json"


def _guide_path(week_start: str) -> Path:
    return _GUIDE_DIR / f"{week_start}.md"


def _minimal_artifact(lesson: dict, reason: str) -> dict:
    return {
        "week_start": lesson.get("week_start", ""),
        "cfm_range": lesson.get("reading", ""),
        "weekly_purpose": "",
        "daily_units": [],
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


def _write_guide(path: Path, guide: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(guide or "").strip() + "\n", encoding="utf-8")


def _normalize_markdown(text: str) -> str:
    text = str(text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
    return text


def _guide_user_content(lesson: dict) -> str:
    return f"""I am studying the 2026 Come, Follow Me lesson below.

Week start: {lesson.get("week_start", "")}
Week end: {lesson.get("week_end", "")}
Date range: {lesson.get("date_range", "")}
Lesson title: {lesson.get("title", "")}
Scripture reading: {lesson.get("reading", "")}
Lesson URL: {lesson.get("lesson_url", "")}
Key scripture: {lesson.get("key_scripture", "")}
Key scripture text: {lesson.get("scripture_text", "")}

Generate the complete weekly markdown study guide."""


def generate_weekly_guide(
    lesson: dict,
    model_config: dict | None,
    *,
    force: bool = False,
) -> Path:
    week_start = str(lesson.get("week_start", "")).strip()
    if not week_start:
        raise ValueError("lesson.week_start is required")
    if not model_config:
        raise ValueError("model_config is required")

    path = _guide_path(week_start)
    if path.exists() and not force:
        return path

    guide = call_llm(
        _GUIDE_SYSTEM_PROMPT,
        _guide_user_content(lesson),
        model_config,
        max_retries=1,
        json_mode=False,
        stream=True,
    )
    guide_text = _normalize_markdown(str(guide))
    if not guide_text:
        raise ValueError("generated guide was empty")

    _write_guide(path, guide_text)
    return path


def _normalize_daily_units(result: dict) -> list[dict]:
    raw_units = result.get("daily_units", []) or []
    if not raw_units:
        raw_units = [
            {
                "id": focus.get("id", ""),
                "kind": "narrative_unit",
                "title": focus.get("text_ref", ""),
                "anchor_ref": focus.get("text_ref", ""),
                "source_refs": [focus.get("text_ref", "")],
                "core_claim": "",
                "supporting_excerpt": focus.get("guide_excerpt", ""),
                "enhancement": "",
                "application": "",
                "prompt_hint": "",
            }
            for focus in (result.get("daily_foci", []) or [])
            if isinstance(focus, dict)
        ]

    daily_units = []
    seen_ids: set[str] = set()
    for idx, unit in enumerate(raw_units, start=1):
        if not isinstance(unit, dict):
            continue
        unit_id = str(unit.get("id") or f"focus-{idx}").strip()
        if not unit_id or unit_id in seen_ids:
            unit_id = f"focus-{idx}"
        seen_ids.add(unit_id)
        kind = str(unit.get("kind", "")).strip().lower() or "narrative_unit"
        if kind not in _VALID_DAILY_UNIT_KINDS:
            kind = "narrative_unit"
        source_refs = [
            str(ref).strip()
            for ref in (unit.get("source_refs", []) or [])
            if str(ref).strip()
        ]
        anchor_ref = str(unit.get("anchor_ref", "")).strip()
        if anchor_ref and anchor_ref not in source_refs:
            source_refs.insert(0, anchor_ref)
        if not anchor_ref and source_refs:
            anchor_ref = source_refs[0]
        daily_units.append(
            {
                "id": unit_id,
                "kind": kind,
                "title": str(unit.get("title", "")).strip(),
                "anchor_ref": anchor_ref,
                "source_refs": source_refs,
                "core_claim": str(unit.get("core_claim", "")).strip(),
                "supporting_excerpt": str(
                    unit.get("supporting_excerpt")
                    or unit.get("guide_excerpt", "")
                ).strip(),
                "enhancement": str(unit.get("enhancement", "")).strip(),
                "application": str(unit.get("application", "")).strip(),
                "prompt_hint": str(unit.get("prompt_hint", "")).strip(),
            }
        )
    return daily_units


def _ensure_misuse_units(daily_units: list[dict], misuses: list[dict]) -> list[dict]:
    daily_units = list(daily_units)
    misuse_count = sum(
        1 for unit in daily_units if unit.get("kind") == "misuse_correction"
    )
    next_idx = len(daily_units) + 1
    for misuse in misuses:
        if misuse_count >= 2:
            break
        title = str(misuse.get("text", "")).strip()
        if not title:
            continue
        if any(
            unit.get("kind") == "misuse_correction"
            and unit.get("title", "").strip() == title
            for unit in daily_units
        ):
            continue
        daily_units.append(
            {
                "id": f"focus-{next_idx}",
                "kind": "misuse_correction",
                "title": title,
                "anchor_ref": "",
                "source_refs": [],
                "core_claim": str(misuse.get("correction", "")).strip(),
                "supporting_excerpt": str(misuse.get("common_use", "")).strip(),
                "enhancement": str(misuse.get("cost_bearer", "")).strip(),
                "application": "Read the passage more carefully before repeating the common use.",
                "prompt_hint": "Write this as a corrective but charitable daily note.",
            }
        )
        misuse_count += 1
        next_idx += 1
    return daily_units


def _derive_daily_foci(daily_units: list[dict]) -> list[dict]:
    daily_foci = []
    for unit in daily_units:
        daily_foci.append(
            {
                "id": unit["id"],
                "text_ref": unit.get("anchor_ref", ""),
                "guide_excerpt": unit.get("supporting_excerpt", ""),
            }
        )
    return daily_foci


def _validate_artifact(result: dict | None, lesson: dict) -> dict:
    if not isinstance(result, dict):
        result = {}

    misuses = [
        {
            "text": str(item.get("text", "")).strip(),
            "common_use": str(item.get("common_use", "")).strip(),
            "correction": str(item.get("correction", "")).strip(),
            "cost_bearer": str(item.get("cost_bearer", "")).strip(),
        }
        for item in (result.get("misuses", []) or [])
        if isinstance(item, dict)
    ]
    daily_units = _ensure_misuse_units(_normalize_daily_units(result), misuses)
    daily_foci = _derive_daily_foci(daily_units)

    valid_ids = {unit["id"] for unit in daily_units}
    proposed_sequence = {}
    raw_sequence = result.get("proposed_sequence", {}) or {}
    if isinstance(raw_sequence, dict):
        for day in _DAYS:
            unit_id = str(raw_sequence.get(day, "")).strip()
            if unit_id in valid_ids:
                proposed_sequence[day] = unit_id

    if daily_units and not proposed_sequence:
        for day, unit in zip(_DAYS, daily_units, strict=False):
            proposed_sequence[day] = unit["id"]

    return {
        "week_start": lesson.get("week_start", ""),
        "cfm_range": str(result.get("cfm_range") or lesson.get("reading", "")),
        "weekly_purpose": str(result.get("weekly_purpose", "")).strip(),
        "daily_units": daily_units,
        "daily_foci": daily_foci,
        "misuses": misuses,
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

    guide_path = _guide_path(week_start)
    if not guide_path.exists():
        try:
            guide_path = generate_weekly_guide(lesson, model_config)
            log.info(f"prepare_spiritual_weekly: generated guide {guide_path.name}")
        except Exception as exc:
            log.warning(f"prepare_spiritual_weekly: guide generation failed: {exc}")
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
