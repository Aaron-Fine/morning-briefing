"""Fetch 'On This Day' historical events from Wikipedia."""

import logging

from sources._http import http_get_json
from utils.time import today_local

log = logging.getLogger(__name__)

WIKI_API = "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday"


def fetch_on_this_day(config: dict) -> dict:
    """Return notable events, births, and deaths for today's date.

    Returns dict: {events: [...], births: [...], selected: [...]}
    Each item: {year, text}
    Includes _diagnostic key when API fails or returns empty.
    """
    history_config = config.get("history", {})
    event_count = history_config.get("event_count", 8)

    today = today_local()
    empty = {"selected": [], "events": [], "month": today.month, "day": today.day}

    url = f"{WIKI_API}/all/{today.month}/{today.day}"
    log.info(f"On This Day: fetching {url} (local date {today.isoformat()})")
    data = http_get_json(
        url,
        headers={"Accept": "application/json"},
        timeout=10,
        label="On This Day",
    )
    if data is None:
        log.warning("On This Day: Wikimedia API returned no data — treating as failed")
        empty["_diagnostic"] = {
            "status": "failed",
            "error": "Wikimedia API returned no data (HTTP or parse failure)",
        }
        return empty

    selected = [
        {"year": item.get("year", ""), "text": item.get("text", "")}
        for item in data.get("selected", [])[:event_count]
    ]
    events = [
        {"year": item.get("year", ""), "text": item.get("text", "")}
        for item in data.get("events", [])[:event_count]
    ]
    result = {
        "selected": selected,
        "events": events,
        "month": today.month,
        "day": today.day,
    }
    if not selected and not events:
        log.warning("On This Day: API succeeded but returned zero events")
        result["_diagnostic"] = {
            "status": "ok_empty",
            "error": "Wikimedia API returned empty events list",
        }
    return result
