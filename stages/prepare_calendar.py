"""Stage: prepare_calendar — deterministic, no LLM.

Assembles the week_ahead event list from structured data in raw_sources:
launches, church_events (General Conference), and US/Utah holidays.
Sorted chronologically, capped at digest.week_ahead.count.

Input:  context["raw_sources"] keys: launches, church_events, holidays
Output: {"calendar": {"events": [...], "count": N}}
"""

import logging
from datetime import datetime

log = logging.getLogger(__name__)

# ISO datetime/date string parse helpers
_FORMATS = [
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
]


def _parse_date(s: str) -> datetime:
    if not s:
        return datetime.max
    for fmt in _FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            # strip tz info so we can compare
            return dt.replace(tzinfo=None)
        except ValueError:
            continue
    return datetime.max


def run(context: dict, config: dict, model_config: dict | None = None, **kwargs) -> dict:
    raw = context.get("raw_sources", {})
    events: list[dict] = []

    # US/Utah holidays
    for h in raw.get("holidays", []):
        events.append({
            "date": h.get("date", ""),
            "event": h.get("event", ""),
            "type": "holiday",
        })

    # Church events (General Conference sessions, etc.)
    for e in raw.get("church_events", []):
        events.append({
            "date": e.get("date", ""),
            "event": e.get("event", ""),
            "description": e.get("description", ""),
            "type": "church",
        })

    # Economic calendar events (Fed meetings, jobs reports, GDP, etc.)
    for ec in raw.get("economic_calendar", []):
        events.append({
            "date": ec.get("date", ""),
            "event": ec.get("event", ""),
            "type": "economic",
            "impact": ec.get("impact", ""),
        })

    # Space launches
    for launch in raw.get("launches", []):
        events.append({
            "date": launch.get("date", ""),
            "event": launch.get("name", "Unnamed launch"),
            "description": launch.get("mission_description", ""),
            "type": "launch",
            "provider": launch.get("provider", ""),
        })

    # Sort by date
    events.sort(key=lambda e: _parse_date(e.get("date", "")))

    count = config.get("digest", {}).get("week_ahead", {}).get("count", 5)
    trimmed = events[:count]

    log.info(f"prepare_calendar: {len(events)} raw events → {len(trimmed)} selected")
    return {"calendar": {"events": trimmed, "count": len(trimmed)}}
