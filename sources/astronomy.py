"""Fetch ISS visible pass predictions and notable sky events.

Uses Open Notify API for ISS passes and a simple ephemeris approach
for major sky events (planets, meteor showers, moon phases).
"""

import logging
from datetime import datetime, timezone
import requests

log = logging.getLogger(__name__)

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
    try:
        # alt=0 (sea level), days=3, min_visibility=120 (2 min)
        url = f"{ISS_PASS_URL}/{lat}/{lon}/0/3/120"
        resp = requests.get(
            url,
            params={"apiKey": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

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

    except Exception as e:
        log.warning(f"N2YO ISS pass fetch failed: {e}")
        return []


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

    This is a static schedule of major astronomical events for 2026.
    For a production version, consider an ephemeris library like skyfield.
    """
    from datetime import date, timedelta

    today = date.today()
    window_end = today + timedelta(days=3)

    # Major 2026 sky events (date, description)
    events_2026 = [
        ("2026-01-03", "Quadrantids meteor shower peaks"),
        ("2026-01-10", "Full Wolf Moon"),
        ("2026-02-09", "Full Snow Moon"),
        ("2026-03-03", "Jupiter-Mercury conjunction"),
        ("2026-03-11", "Full Worm Moon"),
        ("2026-03-29", "Partial solar eclipse (visible from parts of N. America)"),
        ("2026-04-09", "Full Pink Moon"),
        ("2026-04-22", "Lyrids meteor shower peaks"),
        ("2026-05-06", "Eta Aquariids meteor shower peaks"),
        ("2026-05-08", "Full Flower Moon"),
        ("2026-06-07", "Full Strawberry Moon"),
        ("2026-07-06", "Full Buck Moon"),
        ("2026-07-28", "Delta Aquariids meteor shower peaks"),
        ("2026-08-04", "Full Sturgeon Moon"),
        ("2026-08-12", "Perseids meteor shower peaks — best viewing after midnight"),
        ("2026-08-12", "Total lunar eclipse (visible from Americas)"),
        ("2026-09-03", "Full Corn Moon"),
        ("2026-10-02", "Full Harvest Moon"),
        ("2026-10-21", "Orionids meteor shower peaks"),
        ("2026-11-01", "Full Beaver Moon"),
        ("2026-11-17", "Leonids meteor shower peaks"),
        ("2026-12-01", "Full Cold Moon"),
        ("2026-12-13", "Geminids meteor shower peaks — best of the year"),
    ]

    upcoming = []
    for date_str, desc in events_2026:
        event_date = date.fromisoformat(date_str)
        if today <= event_date <= window_end:
            upcoming.append(desc)

    return upcoming
