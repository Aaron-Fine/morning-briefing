"""Return upcoming US federal and Utah state holidays within a date window."""

from datetime import date, timedelta

import holidays


def get_upcoming_holidays(days: int = 10) -> list[dict]:
    """Return US/UT holidays in the next `days` days.

    Returns list of dicts: {date: "YYYY-MM-DD", event: "Holiday Name"}
    Covers federal holidays plus Utah state holidays (e.g. Pioneer Day).
    Includes _diagnostic key when the holidays library fails.
    """
    today = date.today()
    end = today + timedelta(days=days)
    try:
        us_holidays = holidays.country_holidays("US", subdiv="UT", years={today.year, end.year})
    except Exception as exc:
        return [
            {
                "_diagnostic": {
                    "status": "failed",
                    "error": f"holidays library failed: {exc}",
                }
            }
        ]

    results = [
        {"date": d.isoformat(), "event": us_holidays[d]}
        for d in (today + timedelta(n) for n in range(days + 1))
        if d in us_holidays
    ]
    if not results:
        results.append(
            {
                "_diagnostic": {
                    "status": "ok_empty",
                    "error": f"No US/UT holidays in {days}-day window starting {today.isoformat()}",
                }
            }
        )
    return results
