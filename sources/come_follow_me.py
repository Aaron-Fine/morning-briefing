"""Determine the current Come Follow Me lesson and provide a scripture/thought."""

import logging
from datetime import date, timedelta
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load_schedule() -> list[tuple]:
    """Load Come Follow Me schedule from data/come_follow_me_2026.yaml."""
    with open(DATA_DIR / "come_follow_me_2026.yaml") as f:
        raw = yaml.safe_load(f)
    return [
        (str(l["start"]), str(l["end"]), l["num"], l["reading"], l["title"], l["key_scripture"])
        for l in raw
    ]


def _load_conference_dates() -> list[date]:
    """Load General Conference dates from data/general_conference_dates.yaml."""
    with open(DATA_DIR / "general_conference_dates.yaml") as f:
        raw = yaml.safe_load(f)
    return [d if isinstance(d, date) else date.fromisoformat(str(d)) for d in raw]


def _load_scripture_texts() -> dict[str, str]:
    """Load scripture texts from data/scripture_texts.yaml."""
    with open(DATA_DIR / "scripture_texts.yaml") as f:
        return yaml.safe_load(f)


# Loaded from data/ files; see data/*.yaml for sources and notes.
SCHEDULE_2026 = _load_schedule()
GENERAL_CONFERENCE_DATES = _load_conference_dates()
_SCRIPTURE_TEXTS = _load_scripture_texts()


def get_upcoming_church_events(lookahead_days: int = 10) -> list[dict]:
    """Return General Conference sessions within the lookahead window.

    Returns list of dicts: {date, event, description}
    """
    today = date.today()
    cutoff = today + timedelta(days=lookahead_days)
    events = []
    for d in GENERAL_CONFERENCE_DATES:
        if today <= d <= cutoff:
            label = "Saturday" if d.weekday() == 5 else "Sunday"
            season = "Spring" if d.month == 4 else "Fall"
            events.append({
                "date": d.isoformat(),
                "event": f"LDS General Conference — {season} {d.year} ({label})",
                "description": "Worldwide broadcast of LDS General Conference sessions.",
            })
    return events


def get_current_lesson(config: dict) -> dict:
    """Return this week's Come Follow Me lesson info.

    Returns dict: {reading, title, key_scripture, scripture_text, reflection,
                   lesson_url, date_range}
    """
    today = date.today()
    return get_lesson_for_date(config, today)


def get_lesson_for_date(config: dict, target_date: date) -> dict:
    """Return the Come Follow Me lesson for a specific date."""

    for start_str, end_str, num, reading, title, key_ref in SCHEDULE_2026:
        start = date.fromisoformat(start_str)
        end = date.fromisoformat(end_str)
        if start <= target_date <= end:
            lesson_url = (
                f"{config.get('come_follow_me', {}).get('base_url', '')}/{num + 1}"
            )
            return {
                "reading": reading,
                "title": title,
                "key_scripture": key_ref,
                "scripture_text": _get_scripture_text(key_ref),
                "date_range": (
                    f"{start.strftime('%B')} {start.day}–{end.day}"
                    if start.month == end.month
                    else f"{start.strftime('%B')} {start.day}–{end.strftime('%B')} {end.day}"
                ),
                "lesson_url": lesson_url,
                "lesson_num": num,
                "week_start": start.isoformat(),
                "week_end": end.isoformat(),
            }

    # Fallback if no match
    return {
        "reading": "",
        "title": "Come, Follow Me",
        "key_scripture": "",
        "scripture_text": "",
        "date_range": "",
        "lesson_url": "",
        "lesson_num": 0,
    }


def _get_scripture_text(reference: str) -> str:
    """Return the text of a known key scripture from data/scripture_texts.json."""
    return _SCRIPTURE_TEXTS.get(reference, "")
