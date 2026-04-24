"""Stage: prepare_spiritual — render a short daily note from the weekly artifact.

This stage no longer asks the LLM to improvise a new reflection every day.
Instead it selects a typed daily unit from the weekly spiritual artifact and
emits the unit's own prose fields as short paragraphs — no canned English
scaffolds — so the weekly model's voice carries through and the output is
stable across runs.

Input:  context["raw_sources"]["come_follow_me"]
Output: {"spiritual": {reading, title, key_scripture, scripture_text, reflection,
                        date_range, lesson_url, lesson_num}}
"""

import json
import logging
from pathlib import Path

from stages.spiritual_units import normalize_daily_units
from utils.time import now_local

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_WEEKLY_ARTIFACT_DIR = _ROOT / "output" / "artifacts" / "spiritual"
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday")


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


def _units_by_id(weekly: dict) -> dict[str, dict]:
    return {unit["id"]: unit for unit in normalize_daily_units(weekly) if unit.get("id")}


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


def _render_unit(unit: dict) -> str:
    """Emit the weekly model's own prose, one field per paragraph.

    Anchor_ref, title, and other metadata are surfaced elsewhere in the
    template (spiritual-ref, key_scripture); the reflection body is just the
    prose fields concatenated. Contained duplicates are dropped.
    """

    def clean(text: str) -> str:
        return " ".join(str(text or "").split()).strip()

    ordered = [
        clean(unit.get("supporting_excerpt")),
        clean(unit.get("core_claim")),
        clean(unit.get("enhancement")),
        clean(unit.get("application")),
    ]

    paragraphs: list[str] = []
    for text in ordered:
        if not text:
            continue
        if any(text in prior or prior in text for prior in paragraphs):
            continue
        paragraphs.append(text)

    return "\n\n".join(paragraphs)


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
