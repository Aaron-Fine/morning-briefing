"""Stage: prepare_spiritual — render a short daily note from the weekly artifact.

This stage no longer asks the LLM to improvise a new reflection every day.
Instead it selects a typed daily unit from the weekly spiritual artifact and
renders 1-3 short paragraphs deterministically so the output is stable,
week-aligned, and easy to validate.

Input:  context["raw_sources"]["come_follow_me"]
Output: {"spiritual": {reading, title, key_scripture, scripture_text, reflection,
                        date_range, lesson_url, lesson_num}}
"""

import json
import logging
from pathlib import Path

from utils.time import now_local

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_WEEKLY_ARTIFACT_DIR = _ROOT / "output" / "artifacts" / "spiritual"
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday")
_VALID_DAILY_UNIT_KINDS = {
    "narrative_unit",
    "key_scripture",
    "misuse_correction",
    "scholarly_insight",
    "language_context",
    "faithful_application",
}


def _artifact_path(week_start: str) -> Path:
    return _WEEKLY_ARTIFACT_DIR / f"{week_start}_weekly.json"


def _load_weekly_artifact(week_start: str) -> dict | None:
    path = _artifact_path(week_start)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning(f"prepare_spiritual: failed to read weekly artifact {path}: {exc}")
        return None


def _find_latest_weekly_artifact(today=None) -> dict | None:
    today = today or now_local().date()
    if not _WEEKLY_ARTIFACT_DIR.exists():
        return None

    candidates: list[tuple[str, Path]] = []
    for path in _WEEKLY_ARTIFACT_DIR.glob("*_weekly.json"):
        week_start = path.name.removesuffix("_weekly.json")
        if week_start <= today.isoformat():
            candidates.append((week_start, path))

    for _week_start, path in sorted(candidates, reverse=True):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning(f"prepare_spiritual: failed to read weekly artifact {path}: {exc}")
    return None


def _resolve_weekly_artifact(cfm: dict) -> dict | None:
    week_start = str(cfm.get("week_start", "")).strip()
    if week_start:
        weekly = _load_weekly_artifact(week_start)
        if weekly:
            return weekly
    return _find_latest_weekly_artifact()


def _normalize_daily_units(weekly: dict) -> list[dict]:
    raw_units = weekly.get("daily_units", []) or []
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
            for focus in (weekly.get("daily_foci", []) or [])
            if isinstance(focus, dict)
        ]

    units = []
    for idx, unit in enumerate(raw_units, start=1):
        if not isinstance(unit, dict):
            continue
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
        units.append(
            {
                "id": str(unit.get("id") or f"focus-{idx}").strip() or f"focus-{idx}",
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
    return units


def _units_by_id(weekly: dict) -> dict[str, dict]:
    return {unit["id"]: unit for unit in _normalize_daily_units(weekly) if unit.get("id")}


def _select_unit(weekly: dict, today=None) -> dict | None:
    today = today or now_local().date()
    units = _units_by_id(weekly)
    if not units:
        return None

    sequence = weekly.get("proposed_sequence", {}) or {}
    day = today.strftime("%A").lower()
    unit_id = str(sequence.get(day, "")).strip()
    if unit_id in units:
        return units[unit_id]

    ordered_days = list(_DAYS)
    start_idx = ordered_days.index(day) if day in ordered_days else 0
    for fallback_day in ordered_days[start_idx:] + ordered_days[:start_idx]:
        fallback_id = str(sequence.get(fallback_day, "")).strip()
        if fallback_id in units:
            return units[fallback_id]

    return next(iter(units.values()))


def _sentence(text: str, punctuation: str = ".") -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    if cleaned[-1] in ".!?":
        return cleaned
    return cleaned + punctuation


def _join_sentences(*parts: str) -> str:
    return " ".join(part for part in (_sentence(p) for p in parts) if part).strip()


def _render_unit(unit: dict) -> str:
    kind = unit.get("kind", "narrative_unit")
    title = unit.get("title", "")
    anchor_ref = unit.get("anchor_ref", "")
    core_claim = unit.get("core_claim", "")
    supporting_excerpt = unit.get("supporting_excerpt", "")
    enhancement = unit.get("enhancement", "")
    application = unit.get("application", "")

    if kind == "misuse_correction":
        paragraph_one = _join_sentences(
            f"{title} is easy to flatten into a slogan" if title else "",
            supporting_excerpt,
            core_claim,
        )
        paragraph_two = _join_sentences(
            "A better reading takes the text on its own terms",
            enhancement,
            application,
        )
        return "\n\n".join(p for p in (paragraph_one, paragraph_two) if p)

    if kind == "key_scripture":
        paragraph_one = _join_sentences(
            f"{anchor_ref} deserves slow reading" if anchor_ref else title,
            supporting_excerpt,
        )
        paragraph_two = _join_sentences(core_claim, enhancement, application)
        return "\n\n".join(p for p in (paragraph_one, paragraph_two) if p)

    if kind == "scholarly_insight":
        paragraph_one = _join_sentences(
            title or "One useful scholarly insight from this week",
            supporting_excerpt,
        )
        paragraph_two = _join_sentences(core_claim, enhancement, application)
        return "\n\n".join(p for p in (paragraph_one, paragraph_two) if p)

    if kind == "language_context":
        paragraph_one = _join_sentences(
            title or "One language and context note matters here",
            supporting_excerpt,
        )
        paragraph_two = _join_sentences(core_claim, enhancement, application)
        return "\n\n".join(p for p in (paragraph_one, paragraph_two) if p)

    if kind == "faithful_application":
        paragraph_one = _join_sentences(
            title or "This week asks something concrete of us",
            core_claim,
            supporting_excerpt,
        )
        paragraph_two = _join_sentences(enhancement, application)
        return "\n\n".join(p for p in (paragraph_one, paragraph_two) if p)

    paragraph_one = _join_sentences(
        f"{title} comes into focus in {anchor_ref}" if title and anchor_ref else title,
        supporting_excerpt,
    )
    paragraph_two = _join_sentences(core_claim, enhancement, application)
    return "\n\n".join(p for p in (paragraph_one, paragraph_two) if p)


def _clean_reflection(text: str) -> str:
    paragraphs = [" ".join(p.split()) for p in str(text or "").split("\n\n")]
    return "\n\n".join(p for p in paragraphs if p).strip()


def run(context: dict, config: dict, model_config: dict | None = None, **kwargs) -> dict:
    raw = context.get("raw_sources", {})
    cfm = raw.get("come_follow_me", {})

    if not cfm or not cfm.get("reading"):
        log.warning("prepare_spiritual: no Come Follow Me data available")
        return {"spiritual": {}}

    weekly = _resolve_weekly_artifact(cfm)
    unit = None if not weekly or weekly.get("missing_guide") else _select_unit(weekly)
    if weekly and unit:
        reflection = _clean_reflection(_render_unit(unit))
        extra = {
            "weekly_artifact": weekly.get("week_start", ""),
            "focus_id": unit.get("id", ""),
            "text_ref": unit.get("anchor_ref", ""),
            "daily_unit_kind": unit.get("kind", ""),
            "daily_unit_title": unit.get("title", ""),
        }
    else:
        if not weekly:
            log.warning("prepare_spiritual: no weekly artifact found")
        elif weekly.get("missing_guide"):
            log.warning("prepare_spiritual: weekly guide missing")
        else:
            log.warning("prepare_spiritual: no valid daily unit found")
        reflection = ""
        extra = {}

    return {
        "spiritual": {
            **cfm,
            "reflection": reflection,
            **extra,
        }
    }
