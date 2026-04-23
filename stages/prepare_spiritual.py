"""Stage: prepare_spiritual — daily reader for the weekly spiritual artifact.

Prefers the weekly artifact written by prepare_spiritual_weekly, selecting the
focus for the current day from the live JSON file so user sequence edits take
effect on the next run. Falls back to the legacy CFM reflection behavior when
the weekly artifact is missing or minimal.

Input:  context["raw_sources"]["come_follow_me"]
Output: {"spiritual": {reading, title, key_scripture, scripture_text, reflection,
                        date_range, lesson_url, lesson_num}}
"""

import json
import logging
from pathlib import Path

from morning_digest.llm import call_llm
from utils.prompts import load_prompt
from utils.time import now_local

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = load_prompt("prepare_spiritual_system.md")
_ROOT = Path(__file__).resolve().parent.parent
_WEEKLY_ARTIFACT_DIR = _ROOT / "output" / "artifacts" / "spiritual"
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday")


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


def _focus_by_id(weekly: dict) -> dict[str, dict]:
    return {
        str(focus.get("id", "")): focus
        for focus in weekly.get("daily_foci", []) or []
        if isinstance(focus, dict) and focus.get("id")
    }


def _select_focus(weekly: dict, today=None) -> dict | None:
    today = today or now_local().date()
    foci = _focus_by_id(weekly)
    if not foci:
        return None

    sequence = weekly.get("proposed_sequence", {}) or {}
    day = today.strftime("%A").lower()
    focus_id = str(sequence.get(day, "")).strip()
    if focus_id in foci:
        return foci[focus_id]

    if focus_id:
        log.warning(
            f"prepare_spiritual: proposed_sequence[{day!r}] references invalid focus "
            f"{focus_id!r}"
        )
    else:
        log.info(f"prepare_spiritual: no proposed_sequence entry for {day!r}")

    ordered_days = list(_DAYS)
    start_idx = ordered_days.index(day) if day in ordered_days else 0
    for fallback_day in ordered_days[start_idx:] + ordered_days[:start_idx]:
        fallback_id = str(sequence.get(fallback_day, "")).strip()
        if fallback_id in foci:
            return foci[fallback_id]

    return next(iter(foci.values()))


def _related_weekly_material(weekly: dict, focus: dict) -> dict:
    text_ref = str(focus.get("text_ref", "")).lower()

    def related(item: dict) -> bool:
        haystack = " ".join(str(value).lower() for value in item.values())
        return bool(text_ref and text_ref in haystack)

    misuses = [
        item
        for item in weekly.get("misuses", []) or []
        if isinstance(item, dict) and related(item)
    ]
    applications = [
        item
        for item in weekly.get("applications", []) or []
        if isinstance(item, dict) and related(item)
    ]
    return {
        "misuses": misuses or weekly.get("misuses", []) or [],
        "applications": applications or weekly.get("applications", []) or [],
        "conspicuous_absences": weekly.get("conspicuous_absences", []) or [],
    }


def _legacy_user_content(cfm: dict) -> str:
    return (
        f"Week: {cfm.get('date_range', 'This week')}\n"
        f"Reading: {cfm.get('reading', '')}\n"
        f"Title: {cfm.get('title', '')}\n"
        f"Key scripture ({cfm.get('key_scripture', '')}): "
        f"{cfm.get('scripture_text', '')}\n\n"
        f"Write the spiritual thought."
    )


def _weekly_user_content(cfm: dict, weekly: dict, focus: dict) -> str:
    related = _related_weekly_material(weekly, focus)
    return f"""Week: {cfm.get('date_range', 'This week')}
Reading: {cfm.get('reading') or weekly.get('cfm_range', '')}
Title: {cfm.get('title', '')}
Key scripture ({cfm.get('key_scripture', '')}): {cfm.get('scripture_text', '')}

Today's focus:
Text reference: {focus.get('text_ref', '')}
Guide excerpt: {focus.get('guide_excerpt', '')}

Weekly purpose:
{weekly.get('weekly_purpose', '')}

Related misuse/correction material:
{json.dumps(related['misuses'], indent=2)}

Related applications:
{json.dumps(related['applications'], indent=2)}

Conspicuous absences:
{json.dumps(related['conspicuous_absences'], indent=2)}

Write an 80-150 word reflection. Do not mention today's news or make a news-to-scripture comparison."""


def _generate_reflection(user_content: str, model_config: dict | None) -> str:
    if not model_config:
        log.info("prepare_spiritual: no model config, using scripture text only")
        return ""
    try:
        reflection = call_llm(
            _SYSTEM_PROMPT,
            user_content,
            model_config,
            max_retries=1,
            json_mode=False,
            stream=True,
        )
        log.info("prepare_spiritual: reflection generated")
        return reflection.strip()
    except Exception as e:
        log.warning(f"prepare_spiritual: LLM call failed, using scripture text only: {e}")
        return ""


def _sanitize_reflection(reflection: str) -> str:
    """Reject obvious prompt/meta leakage before rendering."""
    cleaned = str(reflection or "").strip()
    if not cleaned:
        return ""

    meta_markers = (
        "the user wants me to",
        "let me craft",
        "i want to avoid",
        "i want to",
        "i need to",
        "write an 80-150 word reflection",
        "write the spiritual thought",
        "today's focus:",
        "weekly purpose:",
        "related misuse",
        "conspicuous absences:",
    )
    lowered = cleaned.lower()
    if any(marker in lowered for marker in meta_markers):
        log.warning("prepare_spiritual: rejected reflection with prompt/meta leakage")
        return ""

    return cleaned


def run(context: dict, config: dict, model_config: dict | None = None, **kwargs) -> dict:
    raw = context.get("raw_sources", {})
    cfm = raw.get("come_follow_me", {})

    if not cfm or not cfm.get("reading"):
        log.warning("prepare_spiritual: no Come Follow Me data available")
        return {"spiritual": {}}

    weekly = _find_latest_weekly_artifact()
    focus = None if not weekly or weekly.get("missing_guide") else _select_focus(weekly)
    if weekly and focus:
        user_content = _weekly_user_content(cfm, weekly, focus)
        reflection = _sanitize_reflection(
            _generate_reflection(user_content, model_config)
        )
        extra = {
            "weekly_artifact": weekly.get("week_start", ""),
            "focus_id": focus.get("id", ""),
            "text_ref": focus.get("text_ref", ""),
        }
    else:
        if not weekly:
            log.warning("prepare_spiritual: no weekly artifact found; using legacy fallback")
        elif weekly.get("missing_guide"):
            log.warning("prepare_spiritual: weekly guide missing; using legacy fallback")
        else:
            log.warning("prepare_spiritual: no valid weekly focus; using legacy fallback")
        reflection = _sanitize_reflection(
            _generate_reflection(_legacy_user_content(cfm), model_config)
        )
        extra = {}

    return {
        "spiritual": {
            **cfm,
            "reflection": reflection.strip() if reflection else cfm.get("scripture_text", ""),
            **extra,
        }
    }
