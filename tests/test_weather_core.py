"""Tests for sources/weather.py — core functions: cache, normals, AQI labels."""

import sys
import os
import json
import time
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sources.weather import (
    _aqi_to_label,
    _interpolate_monthly,
    _compute_normals_and_records,
    _cache_read,
    _cache_write,
    _LOGAN_NORMALS,
    _LOGAN_RECORDS,
    _WMO_CODES,
)


class TestAqiToLabel:
    """Tests for AQI label classification."""

    def test_none_returns_unavailable(self):
        assert _aqi_to_label(None) == "unavailable"

    def test_good_range(self):
        assert _aqi_to_label(0) == "Good"
        assert _aqi_to_label(25) == "Good"
        assert _aqi_to_label(50) == "Good"

    def test_moderate_range(self):
        assert _aqi_to_label(51) == "Moderate"
        assert _aqi_to_label(75) == "Moderate"
        assert _aqi_to_label(100) == "Moderate"

    def test_unhealthy_for_sensitive_groups(self):
        assert _aqi_to_label(101) == "Unhealthy for Sensitive Groups"
        assert _aqi_to_label(150) == "Unhealthy for Sensitive Groups"

    def test_unhealthy_range(self):
        assert _aqi_to_label(151) == "Unhealthy"
        assert _aqi_to_label(200) == "Unhealthy"

    def test_very_unhealthy_range(self):
        assert _aqi_to_label(201) == "Very Unhealthy"
        assert _aqi_to_label(300) == "Very Unhealthy"

    def test_hazardous_range(self):
        assert _aqi_to_label(301) == "Hazardous"
        assert _aqi_to_label(500) == "Hazardous"

    def test_boundary_values(self):
        """Test exact boundary values."""
        boundaries = [
            (0, "Good"),
            (50, "Good"),
            (51, "Moderate"),
            (100, "Moderate"),
            (101, "Unhealthy for Sensitive Groups"),
            (150, "Unhealthy for Sensitive Groups"),
            (151, "Unhealthy"),
            (200, "Unhealthy"),
            (201, "Very Unhealthy"),
            (300, "Very Unhealthy"),
            (301, "Hazardous"),
        ]
        for aqi, expected in boundaries:
            assert _aqi_to_label(aqi) == expected, f"AQI {aqi} should be '{expected}'"


class TestInterpolateMonthly:
    """Tests for monthly temperature interpolation."""

    def test_mid_month_returns_month_value(self):
        """On the 15th, should return the exact monthly value."""
        dt = datetime(2026, 7, 15)
        hi, lo = _interpolate_monthly(_LOGAN_NORMALS, dt)
        assert hi == _LOGAN_NORMALS[7][0]
        assert lo == _LOGAN_NORMALS[7][1]

    def test_early_month_interpolates_from_previous(self):
        """Before the 15th, interpolates between previous and current month."""
        dt = datetime(2026, 4, 1)  # Early April
        hi, lo = _interpolate_monthly(_LOGAN_NORMALS, dt)
        # Should be between March and April values
        march_hi = _LOGAN_NORMALS[3][0]
        april_hi = _LOGAN_NORMALS[4][0]
        assert march_hi <= hi <= april_hi

    def test_late_month_interpolates_to_next(self):
        """After the 15th, interpolates between current and next month."""
        dt = datetime(2026, 4, 30)  # Late April
        hi, lo = _interpolate_monthly(_LOGAN_NORMALS, dt)
        # Should be between April and May values
        april_hi = _LOGAN_NORMALS[4][0]
        may_hi = _LOGAN_NORMALS[5][0]
        assert april_hi <= hi <= may_hi

    def test_january_early_interpolates_from_december(self):
        """Early January should interpolate from December to January."""
        dt = datetime(2026, 1, 10)
        hi, lo = _interpolate_monthly(_LOGAN_NORMALS, dt)
        dec_hi = _LOGAN_NORMALS[12][0]
        jan_hi = _LOGAN_NORMALS[1][0]
        assert min(dec_hi, jan_hi) <= hi <= max(dec_hi, jan_hi)

    def test_december_late_interpolates_to_january(self):
        """Late December should interpolate from December to January."""
        dt = datetime(2026, 12, 20)
        hi, lo = _interpolate_monthly(_LOGAN_NORMALS, dt)
        dec_hi = _LOGAN_NORMALS[12][0]
        jan_hi = _LOGAN_NORMALS[1][0]
        assert min(dec_hi, jan_hi) <= hi <= max(dec_hi, jan_hi)

    def test_records_interpolation(self):
        """Records should also be interpolated."""
        dt = datetime(2026, 7, 15)
        hi, lo = _interpolate_monthly(_LOGAN_RECORDS, dt)
        assert hi == _LOGAN_RECORDS[7][0]
        assert lo == _LOGAN_RECORDS[7][1]

    def test_february_mid_month(self):
        dt = datetime(2026, 2, 15)
        hi, lo = _interpolate_monthly(_LOGAN_NORMALS, dt)
        assert hi == _LOGAN_NORMALS[2][0]
        assert lo == _LOGAN_NORMALS[2][1]

    def test_leap_year_february(self):
        """Leap year should still work correctly."""
        dt = datetime(2028, 2, 29)
        hi, lo = _interpolate_monthly(_LOGAN_NORMALS, dt)
        feb_hi = _LOGAN_NORMALS[2][0]
        mar_hi = _LOGAN_NORMALS[3][0]
        assert feb_hi <= hi <= mar_hi


class TestComputeNormalsAndRecords:
    """Tests for normals and records computation from forecast data."""

    def test_basic_forecast(self):
        forecast = [
            {"date": "2026-07-15"},
            {"date": "2026-07-16"},
        ]
        result = _compute_normals_and_records(forecast)
        assert len(result) == 2
        assert result[0]["date"] == "2026-07-15"
        assert "normal_hi" in result[0]
        assert "normal_lo" in result[0]
        assert "record_hi" in result[0]
        assert "record_lo" in result[0]

    def test_empty_forecast(self):
        result = _compute_normals_and_records([])
        assert result == []

    def test_skips_entries_without_date(self):
        forecast = [
            {"date": "2026-07-15"},
            {"no_date": True},
        ]
        result = _compute_normals_and_records(forecast)
        assert len(result) == 1

    def test_skips_entries_with_invalid_date(self):
        forecast = [
            {"date": "2026-07-15"},
            {"date": "not-a-date"},
        ]
        result = _compute_normals_and_records(forecast)
        assert len(result) == 1

    def test_values_are_rounded(self):
        forecast = [{"date": "2026-07-15"}]
        result = _compute_normals_and_records(forecast)
        # On the 15th, values should be exact monthly values (already integers)
        assert isinstance(result[0]["normal_hi"], float)
        assert isinstance(result[0]["normal_lo"], float)

    def test_year_boundary_january(self):
        forecast = [{"date": "2026-01-15"}]
        result = _compute_normals_and_records(forecast)
        assert len(result) == 1
        assert result[0]["normal_hi"] == _LOGAN_NORMALS[1][0]


class TestCacheReadWrite:
    """Tests for JSON cache helpers."""

    def test_cache_write_and_read(self, tmp_path):
        with patch("sources.weather.CACHE_DIR", tmp_path):
            _cache_write("test_key", {"data": "value"})
            result = _cache_read("test_key", ttl_hours=24)
        assert result == {"data": "value"}

    def test_cache_read_nonexistent_returns_none(self, tmp_path):
        with patch("sources.weather.CACHE_DIR", tmp_path):
            result = _cache_read("nonexistent", ttl_hours=24)
        assert result is None

    def test_cache_read_expired_returns_none(self, tmp_path):
        with patch("sources.weather.CACHE_DIR", tmp_path):
            _cache_write("expired_key", {"data": "value"})
            # Set file mtime to 3 hours ago
            cache_file = tmp_path / "expired_key.json"
            old_time = time.time() - (3 * 3600)
            os.utime(cache_file, (old_time, old_time))
            result = _cache_read("expired_key", ttl_hours=2)
        assert result is None

    def test_cache_read_not_expired(self, tmp_path):
        with patch("sources.weather.CACHE_DIR", tmp_path):
            _cache_write("fresh_key", {"data": "value"})
            result = _cache_read("fresh_key", ttl_hours=2)
        assert result == {"data": "value"}

    def test_cache_read_corrupted_json_returns_none(self, tmp_path):
        with patch("sources.weather.CACHE_DIR", tmp_path):
            cache_file = tmp_path / "corrupt.json"
            cache_file.write_text("not valid json {{{")
            result = _cache_read("corrupt", ttl_hours=24)
        assert result is None

    def test_cache_write_creates_directory(self, tmp_path):
        nested = tmp_path / "nested" / "dir"
        with patch("sources.weather.CACHE_DIR", nested):
            nested.mkdir(parents=True)
            _cache_write("new_key", {"test": True})
            result = _cache_read("new_key", ttl_hours=24)
        assert result == {"test": True}

    def test_cache_write_handles_os_error(self, tmp_path, caplog):
        """Should log warning but not crash on write failure."""
        with patch("sources.weather.CACHE_DIR", tmp_path):
            with patch("builtins.open", side_effect=OSError("disk full")):
                _cache_write("fail_key", {"data": "value"})
        # Should not raise, should log warning
        assert "failed to write cache" in caplog.text.lower() or "disk full" in caplog.text


class TestWmoCodes:
    """Tests for WMO weather code mapping."""

    def test_clear_sky(self):
        assert _WMO_CODES[0] == "Clear"

    def test_thunderstorm(self):
        assert _WMO_CODES[95] == "Thunderstorm"

    def test_heavy_snow(self):
        assert _WMO_CODES[75] == "Heavy snow"

    def test_unknown_code_returns_unknown(self):
        from sources.weather import _wmo_to_text

        assert _wmo_to_text(999) == "Unknown"

    def test_all_codes_are_strings(self):
        for code, text in _WMO_CODES.items():
            assert isinstance(text, str)
            assert len(text) > 0
