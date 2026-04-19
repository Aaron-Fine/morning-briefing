"""Shared local-time helpers for the Morning Digest runtime.

Timezone authority comes from the container ``TZ`` environment variable.
If ``TZ`` is unset or invalid, fall back to UTC.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def get_local_tz() -> ZoneInfo:
    """Return the runtime timezone from ``TZ``, falling back to UTC."""
    tz_name = os.environ.get("TZ", "UTC")
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def now_local() -> datetime:
    """Return a timezone-aware datetime in the runtime local timezone."""
    return datetime.now(get_local_tz())


def today_local() -> date:
    """Return the local calendar date."""
    return now_local().date()


def iso_now_local() -> str:
    """Return an ISO-8601 timestamp in local time."""
    return now_local().isoformat()


def artifact_date() -> str:
    """Return the local date formatted for artifact directory names."""
    return today_local().isoformat()


def format_display_date(dt: datetime | None = None) -> str:
    """Format a user-visible local date without platform-specific strftime flags."""
    current = dt or now_local()
    return f"{current:%A}, {current:%B} {current.day}, {current.year}"


def format_display_time(dt: datetime | None = None) -> str:
    """Format a user-visible local time without platform-specific strftime flags."""
    current = dt or now_local()
    hour = current.hour % 12 or 12
    minute = current.minute
    suffix = "AM" if current.hour < 12 else "PM"
    return f"{hour}:{minute:02d} {suffix}"


def tz_abbrev(dt: datetime | None = None) -> str:
    """Return the local timezone abbreviation, falling back to the zone key."""
    current = dt or now_local()
    return current.tzname() or get_local_tz().key
