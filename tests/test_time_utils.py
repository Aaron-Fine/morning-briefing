"""Tests for shared local-time helpers."""

from datetime import datetime
from zoneinfo import ZoneInfo

from utils.time import (
    artifact_date,
    format_display_date,
    format_display_time,
    get_local_tz,
    tz_abbrev,
)


class TestTimeHelpers:
    def test_get_local_tz_from_env(self, monkeypatch):
        monkeypatch.setenv("TZ", "America/Denver")
        assert get_local_tz().key == "America/Denver"

    def test_invalid_tz_falls_back_to_utc(self, monkeypatch):
        monkeypatch.setenv("TZ", "Invalid/Zone")
        assert get_local_tz().key == "UTC"

    def test_format_display_date(self):
        dt = datetime(2026, 4, 17, 6, 5, tzinfo=ZoneInfo("America/Denver"))
        assert format_display_date(dt) == "Friday, April 17, 2026"

    def test_format_display_time(self):
        dt = datetime(2026, 4, 17, 6, 5, tzinfo=ZoneInfo("America/Denver"))
        assert format_display_time(dt) == "6:05 AM"

    def test_tz_abbrev(self):
        dt = datetime(2026, 4, 17, 6, 5, tzinfo=ZoneInfo("America/Denver"))
        assert tz_abbrev(dt) == "MDT"

    def test_artifact_date_uses_local_tz(self, monkeypatch):
        monkeypatch.setenv("TZ", "UTC")
        assert len(artifact_date()) == 10
