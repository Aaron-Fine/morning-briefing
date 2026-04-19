"""Fetch ISS visible pass predictions and notable sky events.

Uses Open Notify API for ISS passes and a simple ephemeris approach
for major sky events (planets, meteor showers, moon phases).
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from sources._http import http_get_json

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Open Notify ISS pass predictions (free, no key)
ISS_PASS_URL = "https://api.n2yo.com/rest/v1/satellite/visualpasses/25544"

# Fallback: use simple rise/set API
ISS_POSITION_URL = "http://api.open-notify.org/iss-now.json"


def fetch_astronomy(config: dict) -> dict:
    """Return ISS passes and notable sky events.

    Returns dict: {iss_passes: [...], moon_phase: str, events: [...]}
    """
    loc = config.get("location", {})
    lat = loc.get("latitude", 41.737)
    lon = loc.get("longitude", -111.834)

    result = {
        "iss_passes": [],
        "moon_phase": _get_moon_phase(),
        "events": _get_sky_events(),
    }

    # Try N2YO API for ISS visible passes (requires free API key)
    n2yo_key = config.get("astronomy", {}).get("n2yo_api_key", "")
    if n2yo_key:
        result["iss_passes"] = _fetch_iss_passes_n2yo(lat, lon, n2yo_key)
    else:
        # Fallback: just report ISS current position
        result["iss_passes"] = _fetch_iss_simple()

    return result


def _fetch_iss_passes_n2yo(lat: float, lon: float, api_key: str) -> list[dict]:
    """Fetch upcoming visible ISS passes from N2YO."""
    # alt=0 (sea level), days=3, min_visibility=120 (2 min)
    url = f"{ISS_PASS_URL}/{lat}/{lon}/0/3/120"
    data = http_get_json(
        url, params={"apiKey": api_key}, timeout=10, label="N2YO ISS"
    )
    if data is None:
        return []

    passes = []
    for p in data.get("passes", [])[:5]:
        start_utc = datetime.fromtimestamp(p["startUTC"], tz=timezone.utc)
        passes.append({
            "datetime": start_utc.isoformat(),
            "duration_sec": p.get("duration", 0),
            "max_elevation": p.get("maxEl", 0),
            "magnitude": p.get("mag", None),
        })
    return passes


def _fetch_iss_simple() -> list[dict]:
    """Simple fallback: just note that ISS pass data requires N2YO key."""
    return []


def _get_moon_phase() -> str:
    """Calculate approximate moon phase for today.

    Uses a simple algorithm based on the known new moon of Jan 6, 2000.
    """
    from datetime import date

    today = date.today()
    # Known new moon: January 6, 2000
    known_new_moon = date(2000, 1, 6)
    days_since = (today - known_new_moon).days
    lunation = days_since % 29.53058867

    if lunation < 1.85:
        return "New Moon"
    elif lunation < 5.53:
        return "Waxing Crescent"
    elif lunation < 9.22:
        return "First Quarter"
    elif lunation < 12.91:
        return "Waxing Gibbous"
    elif lunation < 16.61:
        return "Full Moon"
    elif lunation < 20.30:
        return "Waning Gibbous"
    elif lunation < 23.99:
        return "Last Quarter"
    elif lunation < 27.68:
        return "Waning Crescent"
    else:
        return "New Moon"


def _get_sky_events() -> list[str]:
    """Return notable sky events for the current period.

    Loads events from data/astronomy_events_2026.yaml.
    For a production version, consider an ephemeris library like skyfield.
    """
    from datetime import date, timedelta

    today = date.today()
    window_end = today + timedelta(days=3)

    with open(DATA_DIR / "astronomy_events_2026.yaml") as f:
        raw = yaml.safe_load(f)

    upcoming = []
    for entry in raw:
        event_date = entry["date"] if isinstance(entry["date"], date) else date.fromisoformat(str(entry["date"]))
        if today <= event_date <= window_end:
            upcoming.append(entry["description"])

    return upcoming
