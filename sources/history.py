"""Fetch 'On This Day' historical events from Wikipedia."""

import logging
from datetime import datetime
import requests

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

    try:
        resp = requests.get(
            f"{WIKI_API}/all/{today.month}/{today.day}",
            headers={
                "User-Agent": "MorningDigest/1.0",
                "Accept": "application/json",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        # "selected" contains editorially curated events — best quality
        selected = []
        for item in data.get("selected", [])[:event_count]:
            selected.append({
                "year": item.get("year", ""),
                "text": item.get("text", ""),
            })

        # Also grab a few notable events
        events = []
        for item in data.get("events", [])[:event_count]:
            events.append({
                "year": item.get("year", ""),
                "text": item.get("text", ""),
            })

        return {
            "selected": selected,
            "events": events,
            "month": today.month,
            "day": today.day,
        }

    except Exception as e:
        log.warning(f"On This Day fetch failed: {e}")
        return {"selected": [], "events": [], "month": today.month, "day": today.day}
