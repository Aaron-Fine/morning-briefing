"""Fetch upcoming space launches from Launch Library 2 (no API key required)."""

import logging
from datetime import datetime, timedelta, timezone

from sources._http import http_get_json

log = logging.getLogger(__name__)

LAUNCH_LIBRARY_URL = "https://ll.thespacedevs.com/2.2.0/launch/upcoming/"

# Mission types to treat as elevated priority in sort order
HIGH_PRIORITY_TYPES = {"government", "military", "classified"}


def fetch_upcoming_launches(lookahead_days: int = 10) -> list[dict]:
    """Return upcoming space launches within the next lookahead_days.

    Returns list of dicts: {name, vehicle, provider, date, launch_site, mission_type,
                            mission_description, status}
    Sorted with government/military missions first, then by date.
    """
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=lookahead_days)

    data = http_get_json(
        LAUNCH_LIBRARY_URL,
        params={"format": "json", "limit": 25, "ordering": "net"},
        label="Launch Library",
    )
    if data is None:
        return []

    launches = []
    for r in data.get("results", []):
        net_str = r.get("net", "")
        if not net_str:
            continue
        net = datetime.fromisoformat(net_str.replace("Z", "+00:00"))
        if net > cutoff:
            break  # results are ordered by date

        mission = r.get("mission") or {}
        mission_type = (mission.get("type") or "").lower()

        launches.append({
            "name": r.get("name", ""),
            "vehicle": r.get("rocket", {}).get("configuration", {}).get("full_name", ""),
            "provider": r.get("launch_service_provider", {}).get("name", ""),
            "date": net.strftime("%Y-%m-%d %H:%MZ"),
            "launch_site": _get_launch_site(r),
            "mission_type": mission_type or "unknown",
            "mission_description": (mission.get("description") or "")[:300],
            "status": r.get("status", {}).get("name", ""),
        })

    # Sort: government/military first, then chronological
    launches.sort(key=lambda x: (
        0 if x["mission_type"] in HIGH_PRIORITY_TYPES else 1,
        x["date"],
    ))

    log.info(f"  Upcoming launches: {len(launches)} in next {lookahead_days} days")
    return launches


def _get_launch_site(result: dict) -> str:
    pad = result.get("pad") or {}
    location = pad.get("location") or {}
    pad_name = pad.get("name", "")
    loc_name = location.get("name", "")
    if pad_name and loc_name:
        return f"{pad_name}, {loc_name}"
    return pad_name or loc_name
