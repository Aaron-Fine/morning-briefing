"""Return upcoming US federal and Utah state holidays within a date window."""

import logging
from datetime import date, timedelta

import holidays

log = logging.getLogger(__name__)

# Utah state holidays beyond federal: Pioneer Day (Jul 24)
_SUBDIV = "UT"


def get_upcoming_holidays(days: int = 10) -> list[dict]:
    """Return US/UT holidays in the next `days` days.

    Returns list of dicts: {date: "YYYY-MM-DD", event: "Holiday Name"}
    """
    today = date.today()
    end = today + timedelta(days=days)

    us_holidays = holidays.country_holidays("US", subdiv=_SUBDIV, years=[today.year, end.year])

    results = []
    current = today
    while current <= end:
        name = us_holidays.get(current)
        if name:
            results.append({"date": current.isoformat(), "event": name})
        current += timedelta(days=1)

    return results
