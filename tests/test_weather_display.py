"""Tests for weather display HTML chart rendering and helpers."""

import json
import os
import pytest

from modules.weather_display import (
    render_weather_html,
    _build_header_html,
    _build_legend_html,
    _build_chart_html,
    _build_text_fallback,
    _temp_to_pct,
    _aqi_position_pct,
    _aqi_color,
    _precip_color,
    _precip_marker,
    _shorten_condition,
    DAY_COUNT,
    AQI_SCALE_MAX,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return json.load(f)


def _make_config(**overrides):
    config = {
        "weather": {
            "aqi_strip": True,
            "record_band": True,
            "normal_band": True,
        }
    }
    config["weather"].update(overrides)
    return config



class TestPrecipMarker:
    """Precipitation type emoji/text markers."""

    def test_thunderstorm(self):
        assert _precip_marker("thunderstorm") == "⚡"

    def test_snow(self):
        assert _precip_marker("snow") == "❄"

    def test_mix(self):
        assert _precip_marker("mix") == "🌨"

    def test_freezing_rain(self):
        assert _precip_marker("freezing_rain") == "frz"

    def test_rain(self):
        assert _precip_marker("rain") == ""

    def test_none(self):
        assert _precip_marker("none") == ""

    def test_unknown(self):
        assert _precip_marker("hail") == ""


class TestShortenCondition:
    """Condition text shortening."""

    def test_thunderstorm(self):
        assert _shorten_condition("Thunderstorm likely") == "T-storm"

    def test_snow_and_rain(self):
        assert _shorten_condition("Snow and rain mix") == "Mix"

    def test_snow(self):
        assert _shorten_condition("Heavy snow") == "Snow"

    def test_rain(self):
        assert _shorten_condition("Rain showers") == "Shwrs"

    def test_clear(self):
        assert _shorten_condition("Clear skies") == "Sunny"

    def test_sunny(self):
        assert _shorten_condition("Sunny") == "Sunny"

    def test_cloudy(self):
        assert _shorten_condition("Mostly cloudy") == "Cloudy"

    def test_fog(self):
        assert _shorten_condition("Dense fog") == "Fog"

    def test_long_condition(self):
        result = _shorten_condition("Partly cloudy with a chance of showers")
        assert result == "Shwrs"  # "shower" triggers the rain/shower path

    def test_empty(self):
        assert _shorten_condition("") == ""


class TestBuildHeaderHtml:
    """Header HTML generation."""

    def test_complete_data(self):
        weather = {
            "city": "Logan",
            "state": "UT",
            "current_temp_f": 72,
            "condition": "Clear",
            "aqi": 26,
            "aqi_label": "Good",
            "wind_mph": 8,
            "humidity": 35,
        }
        html = _build_header_html(weather)
        assert "Logan, UT" in html
        assert "72°F" in html
        assert "Clear" in html
        assert "AQI 26" in html
        assert "Wind 8 mph" in html
        assert "Humidity 35%" in html

    def test_missing_temp(self):
        weather = {
            "city": "Logan",
            "state": "UT",
            "current_temp_f": None,
            "condition": "N/A",
        }
        html = _build_header_html(weather)
        assert "—°F" in html

    def test_missing_wind(self):
        weather = {"city": "Logan", "state": "UT", "wind_mph": None}
        html = _build_header_html(weather)
        assert "Wind calm" in html

    def test_aqi_alert_red(self):
        weather = {
            "city": "Logan",
            "state": "UT",
            "aqi": 160,
            "aqi_label": "Unhealthy",
        }
        html = _build_header_html(weather)
        assert "Red Action Day" in html
        assert "#d32f2f" in html

    def test_aqi_alert_purple(self):
        weather = {
            "city": "Logan",
            "state": "UT",
            "aqi": 250,
            "aqi_label": "Very Unhealthy",
        }
        html = _build_header_html(weather)
        assert "Purple Action Day" in html
        assert "#8f3f97" in html

    def test_aqi_alert_maroon(self):
        weather = {
            "city": "Logan",
            "state": "UT",
            "aqi": 350,
            "aqi_label": "Hazardous",
        }
        html = _build_header_html(weather)
        assert "Maroon Action Day" in html
        assert "#7e0023" in html

    def test_no_aqi_alert_good(self):
        weather = {"city": "Logan", "state": "UT", "aqi": 26, "aqi_label": "Good"}
        html = _build_header_html(weather)
        assert "Action Day" not in html


class TestBuildLegendHtml:
    """Legend HTML generation."""

    def test_default_shows_all(self):
        weather = {"aqi": 26}
        html = _build_legend_html(weather, show_aqi=True, show_records=True)
        assert "Forecast Hi" in html
        assert "Forecast Lo" in html
        assert "Normal" in html
        assert "Record" in html
        assert "Precip" in html
        assert "AQI" in html

    def test_hide_aqi(self):
        weather = {}
        html = _build_legend_html(weather, show_aqi=False, show_records=True)
        assert "AQI" not in html

    def test_hide_records(self):
        weather = {}
        html = _build_legend_html(weather, show_aqi=True, show_records=False)
        assert "Record" not in html


class TestBuildTextFallback:
    """Text fallback when SVG fails."""

    def test_basic_fallback(self):
        weather = {
            "city": "Logan",
            "state": "UT",
            "current_temp_f": 72,
            "condition": "Clear",
            "forecast": [
                {"day_name": "Mon", "high_f": 75, "low_f": 50, "condition": "Sunny"},
                {"day_name": "Tue", "high_f": 70, "low_f": 48, "condition": "Cloudy"},
            ],
        }
        html = _build_text_fallback(weather)
        assert "Logan, UT" in html
        assert "72°F" in html
        assert "Mon:" in html
        assert "Tue:" in html

    def test_empty_forecast(self):
        weather = {"city": "Logan", "state": "UT", "forecast": []}
        html = _build_text_fallback(weather)
        assert "<p>" in html


class TestRenderWeatherHtml:
    """Full render_weather_html integration tests."""

    def test_empty_weather(self):
        assert render_weather_html({}, _make_config()) == ""

    def test_no_forecast(self):
        assert render_weather_html({"city": "Logan"}, _make_config()) == ""

    def test_clear_skies_fixture(self):
        weather = _load_fixture("weather_clear.json")
        html = render_weather_html(weather, _make_config())
        assert "<table" in html
        assert "Logan, UT" in html
        assert "AQI 26" in html

    def test_inversion_fixture(self):
        weather = _load_fixture("weather_inversion.json")
        html = render_weather_html(weather, _make_config())
        assert "<table" in html
        assert "Action Day" in html

    def test_snow_fixture(self):
        weather = _load_fixture("weather_snow.json")
        html = render_weather_html(weather, _make_config())
        assert "<table" in html
        assert "❄" in html

    def test_thunderstorm_fixture(self):
        weather = _load_fixture("weather_thunderstorm.json")
        html = render_weather_html(weather, _make_config())
        assert "<table" in html
        assert "⚡" in html

    def test_mixed_fixture(self):
        weather = _load_fixture("weather_mixed.json")
        html = render_weather_html(weather, _make_config())
        assert "<table" in html
        assert "🌨" in html

    def test_minimal_fixture(self):
        weather = _load_fixture("weather_minimal.json")
        html = render_weather_html(weather, _make_config())
        assert "<table" in html
        assert "Logan, UT" in html

    def test_missing_aqi_fixture(self):
        weather = _load_fixture("weather_missing_aqi.json")
        html = render_weather_html(weather, _make_config())
        assert "<table" in html

    def test_no_svg_in_output(self):
        weather = _load_fixture("weather_clear.json")
        html = render_weather_html(weather, _make_config())
        assert "<svg" not in html
        assert "viewBox" not in html

    def test_aqi_strip_disabled(self):
        weather = _load_fixture("weather_clear.json")
        html = render_weather_html(weather, _make_config(aqi_strip=False))
        # AQI numbers should still appear on bar (aqi_strip only controls legend)
        assert "<table" in html

    def test_record_band_disabled(self):
        weather = _load_fixture("weather_clear.json")
        html = render_weather_html(weather, _make_config(record_band=False))
        assert "<table" in html
        # Record ticks removed from chart; legend hides Record swatch too
        chart_html = _build_chart_html(weather, show_records=False, show_normals=True)
        assert "211,47,47" not in chart_html

    def test_normal_band_disabled(self):
        weather = _load_fixture("weather_clear.json")
        html = render_weather_html(weather, _make_config(normal_band=False))
        assert "<table" in html
        # Normal ticks removed from chart; legend swatch still present
        chart_html = _build_chart_html(weather, show_records=True, show_normals=False)
        assert "100,160,100" not in chart_html

    def test_exception_falls_back_to_text(self):
        """Force an exception by passing bad data."""
        weather = {"forecast": [{"high_f": "not_a_number"}]}
        html = render_weather_html(weather, _make_config())
        assert isinstance(html, str)


class TestTempToPct:
    """Temperature to percentage position on the bar."""

    def test_at_min(self):
        assert _temp_to_pct(30, 30, 80) == 0.0

    def test_at_max(self):
        assert _temp_to_pct(80, 30, 80) == 100.0

    def test_midpoint(self):
        assert _temp_to_pct(55, 30, 80) == 50.0

    def test_equal_range(self):
        assert _temp_to_pct(50, 50, 50) == 50.0

    def test_below_min(self):
        """Below min should clamp to 0."""
        assert _temp_to_pct(20, 30, 80) == 0.0

    def test_above_max(self):
        """Above max should clamp to 100."""
        assert _temp_to_pct(90, 30, 80) == 100.0


class TestAqiPositionPct:
    """AQI value to percentage on 0-200 scale."""

    def test_zero(self):
        assert _aqi_position_pct(0) == 0.0

    def test_hundred(self):
        assert _aqi_position_pct(100) == 50.0

    def test_two_hundred(self):
        assert _aqi_position_pct(200) == 100.0

    def test_above_200_pins(self):
        """Values above 200 pin to 100%."""
        assert _aqi_position_pct(300) == 100.0

    def test_moderate(self):
        assert _aqi_position_pct(57) == pytest.approx(28.5)


class TestAqiColor:
    """AQI value to display color."""

    def test_good(self):
        assert _aqi_color(26) == "#00e400"

    def test_moderate(self):
        assert _aqi_color(57) == "#cccc00"

    def test_usg(self):
        assert _aqi_color(120) == "#ff7e00"

    def test_unhealthy(self):
        assert _aqi_color(175) == "#ff0000"

    def test_very_unhealthy(self):
        assert _aqi_color(220) == "#8f3f97"

    def test_hazardous(self):
        assert _aqi_color(350) == "#7e0023"

    def test_none(self):
        assert _aqi_color(None) == "#888582"


class TestPrecipColor:
    """Precipitation type to bar color."""

    def test_rain(self):
        assert _precip_color("rain") == "#5b9bd5"

    def test_snow(self):
        assert _precip_color("snow") == "#a0d4f0"

    def test_thunderstorm(self):
        assert _precip_color("thunderstorm") == "#5b9bd5"

    def test_mix(self):
        assert _precip_color("mix") == "#5b9bd5"

    def test_freezing_rain(self):
        assert _precip_color("freezing_rain") == "#5b9bd5"

    def test_none(self):
        assert _precip_color("none") == "#5b9bd5"


class TestBuildChartHtml:
    """HTML chart table rendering."""

    def test_returns_table(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        assert "<table" in html
        assert "</table>" in html

    def test_contains_day_labels(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        assert "TUE" in html
        assert "WED" in html

    def test_contains_hi_lo_temps(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        assert "75&deg;" in html or "75°" in html  # hi temp for day 1
        assert "48&deg;" in html or "48°" in html  # lo temp for day 1

    def test_contains_aqi_number(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        # AQI 26 from fixture should appear as text on the bar
        assert ">26<" in html

    def test_contains_precip_bar(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        # Day 6 (Sun) has 60% precip
        assert "60%" in html

    def test_contains_record_ticks(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        # Record ticks use red color
        assert "211,47,47" in html

    def test_contains_normal_ticks(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        # Normal ticks use green color
        assert "100,160,100" in html

    def test_no_records_when_disabled(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=False, show_normals=True)
        assert "211,47,47" not in html

    def test_no_normals_when_disabled(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=False)
        assert "100,160,100" not in html

    def test_no_svg(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        assert "<svg" not in html

    def test_condition_text(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        assert "Sunny" in html

    def test_precip_marker_snow(self):
        weather = _load_fixture("weather_snow.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        assert "❄" in html

    def test_precip_marker_thunderstorm(self):
        weather = _load_fixture("weather_thunderstorm.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        assert "⚡" in html

    def test_aqi_above_200_pins(self):
        """AQI values above 200 should pin to right side of bar."""
        weather = _load_fixture("weather_inversion.json")
        # Modify a day to have AQI > 200
        weather["aqi_forecast"]["2026-01-17"]["aqi"] = 250
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        # Should contain "right:" positioning for pinned AQI
        assert "250" in html

    def test_minimal_data(self):
        """Minimal fixture with 2 days, no AQI."""
        weather = _load_fixture("weather_minimal.json")
        html = _build_chart_html(weather, show_records=True, show_normals=True)
        assert "<table" in html
        assert "FRI" in html


class TestBuildLegendHtmlUpdated:
    """Legend should include Record swatch."""

    def test_has_record_swatch(self):
        weather = {"aqi": 26}
        html = _build_legend_html(weather, show_aqi=True, show_records=True)
        assert "Record" in html
        assert "211,47,47" in html  # red color for record

    def test_no_record_when_disabled(self):
        weather = {}
        html = _build_legend_html(weather, show_aqi=True, show_records=False)
        assert "Record" not in html

    def test_has_precip_swatch(self):
        weather = {}
        html = _build_legend_html(weather, show_aqi=True, show_records=True)
        assert "Precip" in html
