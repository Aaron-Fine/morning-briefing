"""Tests for precipitation classification and timing extraction."""

import pytest

from sources.weather import _classify_precip, _extract_precip_timing


class TestClassifyPrecip:
    """Tests for _classify_precip classification logic."""

    def test_clear_skies(self):
        result = _classify_precip("Sunny", "Sunny, with a high near 75.", 75, 48)
        assert result == "none"

    def test_rain(self):
        result = _classify_precip(
            "Rain", "Rain likely. Cloudy, with a high near 60.", 60, 40
        )
        assert result == "rain"

    def test_light_rain(self):
        result = _classify_precip(
            "Light rain", "A chance of light rain in the afternoon.", 55, 38
        )
        assert result == "rain"

    def test_snow(self):
        result = _classify_precip(
            "Snow", "Snow expected. Accumulation of 2-4 inches.", 32, 20
        )
        assert result == "snow"

    def test_heavy_snow(self):
        result = _classify_precip(
            "Heavy snow", "Heavy snow. Blizzard conditions possible.", 28, 15
        )
        assert result == "snow"

    def test_flurries(self):
        result = _classify_precip("Flurries", "A few flurries in the morning.", 30, 18)
        assert result == "snow"

    def test_thunderstorm(self):
        result = _classify_precip(
            "T-storms", "Thunderstorms possible in the afternoon.", 85, 62
        )
        assert result == "thunderstorm"

    def test_thunder(self):
        result = _classify_precip("Thunder", "Thunder and lightning expected.", 80, 60)
        assert result == "thunderstorm"

    def test_freezing_rain(self):
        result = _classify_precip(
            "Freezing rain", "Freezing rain expected. Ice accumulation.", 30, 25
        )
        assert result == "freezing_rain"

    def test_sleet(self):
        result = _classify_precip("Sleet", "Sleet developing this evening.", 31, 24)
        assert result == "freezing_rain"

    def test_mix_rain_and_snow(self):
        result = _classify_precip(
            "Rain and snow", "Rain and snow mix expected.", 34, 26
        )
        assert result == "mix"

    def test_mix_wintry_mix(self):
        result = _classify_precip("Wintry mix", "Wintry mix of precipitation.", 33, 25)
        assert result == "mix"

    def test_mix_snow_and_rain(self):
        result = _classify_precip(
            "Snow and rain", "Snow and rain throughout the day.", 35, 28
        )
        assert result == "mix"

    def test_drizzle(self):
        result = _classify_precip("Drizzle", "Light drizzle in the morning.", 45, 38)
        assert result == "rain"

    def test_showers(self):
        result = _classify_precip("Showers", "Showers in the afternoon.", 60, 42)
        assert result == "rain"

    def test_priority_freezing_over_snow(self):
        """Freezing rain should take priority over snow."""
        result = _classify_precip(
            "Freezing rain and snow", "Freezing rain developing, then snow.", 28, 18
        )
        assert result == "freezing_rain"

    def test_priority_mix_over_thunderstorm(self):
        """Mix should take priority over thunderstorm."""
        result = _classify_precip(
            "Thunderstorm with wintry mix", "T-storm possible, then wintry mix.", 35, 28
        )
        assert result == "mix"

    def test_priority_thunderstorm_over_snow(self):
        """When both thunder and snow keywords present, mix takes priority (has_snow and has_rain)."""
        result = _classify_precip(
            "Thunderstorm and snow", "Thunderstorm with snow showers possible.", 30, 20
        )
        assert result == "mix"

    def test_priority_snow_over_rain(self):
        """Snow should take priority over rain when both present."""
        result = _classify_precip(
            "Snow and rain", "Snow changing to rain in the afternoon.", 34, 28
        )
        assert result == "mix"

    def test_empty_forecast(self):
        result = _classify_precip("", "", None, None)
        assert result == "none"

    def test_none_temps(self):
        result = _classify_precip("Rain", "Rain expected.", None, None)
        assert result == "rain"


class TestExtractPrecipTiming:
    """Tests for _extract_precip_timing extraction logic."""

    def test_afternoon(self):
        result = _extract_precip_timing("Rain in the afternoon.")
        assert result == "PM"

    def test_after_noon(self):
        result = _extract_precip_timing("Chance of rain after noon.")
        assert result == "PM"

    def test_morning(self):
        result = _extract_precip_timing("Snow in the morning.")
        assert result == "AM"

    def test_before_noon(self):
        result = _extract_precip_timing("Rain before noon.")
        assert result == "AM"

    def test_evening(self):
        result = _extract_precip_timing("Thunderstorms in the evening.")
        assert result == "eve"

    def test_after_midnight(self):
        result = _extract_precip_timing("Snow after midnight.")
        assert result == "eve"

    def test_night(self):
        result = _extract_precip_timing("Mainly cloudy at night.")
        assert result == "night"

    def test_no_timing(self):
        result = _extract_precip_timing("Sunny and clear.")
        assert result == ""

    def test_empty_string(self):
        result = _extract_precip_timing("")
        assert result == ""
