"""Fetch 'On This Day' historical events from Wikipedia."""

import logging
from datetime import datetime

from sources._http import http_get_json

log = logging.getLogger(__name__)

WIKI_API = "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday"


def fetch_on_this_day(config: dict) -> dict:
    """Return notable events, births, and deaths for today's date.

    Returns dict: {events: [...], births: [...], selected: [...]}
    Each item: {year, text}
    """
    history_config = config.get("history", {})
    event_count = history_config.get("event_count", 8)

    today = datetime.now()
    empty = {"selected": [], "events": [], "month": today.month, "day": today.day}

    data = http_get_json(
        f"{WIKI_API}/all/{today.month}/{today.day}",
        headers={"Accept": "application/json"},
        timeout=10,
        label="On This Day",
    )
    if data is None:
        return empty

    selected = [
        {"year": item.get("year", ""), "text": item.get("text", "")}
        for item in data.get("selected", [])[:event_count]
    ]
    events = [
        {"year": item.get("year", ""), "text": item.get("text", "")}
        for item in data.get("events", [])[:event_count]
    ]
    return {
        "selected": selected,
        "events": events,
        "month": today.month,
        "day": today.day,
    }
