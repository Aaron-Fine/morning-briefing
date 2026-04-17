"""Fetch upcoming economic calendar events via Finnhub API."""

import os
import logging
from datetime import datetime, timedelta, timezone

from sources._http import http_get_json

log = logging.getLogger(__name__)

FINNHUB_CALENDAR_URL = "https://finnhub.io/api/v1/calendar/economic"
INCLUDED_IMPACTS = {"high", "medium"}


def fetch_economic_calendar(config: dict) -> list[dict]:
    """Return upcoming US economic events for the next 7 days.

    Returns list of dicts: {date, time, event, impact}
    Filtered to US events with high or medium market impact, sorted by date.
    """
    api_key = os.environ.get("FINNHUB_API_KEY", "")
    if not api_key:
        log.warning("FINNHUB_API_KEY not set — economic calendar unavailable")
        return []

    today = datetime.now(timezone.utc).date()
    through = today + timedelta(days=7)

    data = http_get_json(
        FINNHUB_CALENDAR_URL,
        params={
            "from": today.isoformat(),
            "to": through.isoformat(),
            "token": api_key,
        },
        timeout=10,
        label="Economic calendar",
    )
    if data is None:
        return []

    results = []
    for e in data.get("economicCalendar", []):
        if e.get("country", "").upper() != "US":
            continue
        impact = e.get("impact", "").lower()
        if impact not in INCLUDED_IMPACTS:
            continue
        results.append({
            "date": e.get("time", "")[:10],
            "time": e.get("time", "")[11:16],
            "event": e.get("event", ""),
            "impact": impact,
        })

    results.sort(key=lambda x: x["date"])
    log.info(f"  Economic calendar: {len(results)} upcoming US events")
    return results
