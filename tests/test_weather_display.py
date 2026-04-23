"""Tests for weather display HTML chart rendering and helpers."""

import json
import os
import pytest

from modules.weather_display import (
    render_weather_html,
    _build_header_html,
    _build_chart_html,
    _build_legend_html,
    _build_text_fallback,
    _temp_to_pct,
    _aqi_text_color,
    _precip_color,
    _precip_marker,
    _shorten_condition,
    AQI_SCALE_MAX,
    DAY_COUNT,
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

    def test_aqi_colored_bold(self):
        """AQI should render as a bold colored span, not plain text."""
        weather = {"city": "Logan", "state": "UT", "aqi": 26, "aqi_label": "Good"}
        html = _build_header_html(weather)
        assert "font-weight:700" in html
        assert "#15803d" in html  # Good AQI text color

    def test_no_aqi_alert_good(self):
        weather = {"city": "Logan", "state": "UT", "aqi": 26, "aqi_label": "Good"}
        html = _build_header_html(weather)
        assert "Action Day" not in html


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

    def test_band_flags_accepted(self):
        """Band flags gate the optional overlays without disabling the chart."""
        weather = _load_fixture("weather_clear.json")
        html = render_weather_html(
            weather,
            _make_config(aqi_strip=False, record_band=False, normal_band=False),
        )
        assert "<table" in html
        # Legend and per-bar AQI numbers should be suppressed.
        assert "Moderate" not in html
        assert "wx-record-band" not in html
        assert "wx-normal-band" not in html
        for aqi_val in (e["aqi"] for e in weather["aqi_forecast"].values()):
            assert f">{aqi_val}<" not in html

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


class TestAqiTextColor:
    """Readable text colors for AQI inline display."""

    def test_good(self):
        assert _aqi_text_color(26) == "#15803d"

    def test_moderate(self):
        assert _aqi_text_color(57) == "#854d0e"

    def test_usg(self):
        assert _aqi_text_color(120) == "#c2410c"

    def test_unhealthy(self):
        assert _aqi_text_color(175) == "#dc2626"

    def test_very_unhealthy(self):
        assert _aqi_text_color(220) == "#7c3aed"

    def test_hazardous(self):
        assert _aqi_text_color(350) == "#991b1b"

    def test_none(self):
        assert _aqi_text_color(None) == "#666666"


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
        html = _build_chart_html(weather)
        assert "<table" in html
        assert "</table>" in html

    def test_contains_day_labels(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather)
        assert "TUE" in html
        assert "WED" in html

    def test_contains_hi_lo_temps(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather)
        assert "75&deg;" in html or "75°" in html  # hi temp for day 1
        assert "48&deg;" in html or "48°" in html  # lo temp for day 1

    def test_contains_precip_bar(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather)
        # Day 6 (Sun) has 60% precip
        assert "60%" in html

    def test_no_svg(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather)
        assert "<svg" not in html

    def test_condition_text(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather)
        assert "Sunny" in html

    def test_precip_marker_snow(self):
        weather = _load_fixture("weather_snow.json")
        html = _build_chart_html(weather)
        assert "❄" in html

    def test_precip_marker_thunderstorm(self):
        weather = _load_fixture("weather_thunderstorm.json")
        html = _build_chart_html(weather)
        assert "⚡" in html

    def test_minimal_data(self):
        """Minimal fixture with 2 days, no AQI."""
        weather = _load_fixture("weather_minimal.json")
        html = _build_chart_html(weather)
        assert "<table" in html
        assert "FRI" in html

    def test_repeated_chart_cells_use_css_classes(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather)
        assert 'class="wx-day-cell"' in html
        assert 'class="wx-temp-cell wx-lo-temp"' in html
        assert 'class="wx-gradient-cell"' in html
        assert 'class="wx-condition-cell"' in html
        assert "width:32px;font-size:9px" not in html
        assert "width:60px;font-size:9px" not in html


class TestRightColumn:
    """Right column shows condition + precip% together, not either/or."""

    def test_condition_and_precip_both_present(self):
        weather = {
            "forecast": [
                {
                    "day_name": "Mon",
                    "high_f": 50,
                    "low_f": 30,
                    "condition": "Rain showers",
                    "precip_chance": 60,
                    "precip_type": "rain",
                }
            ]
        }
        html = _build_chart_html(weather)
        assert "Shwrs" in html  # shortened condition
        assert "60%" in html

    def test_condition_only_when_no_precip(self):
        weather = {
            "forecast": [
                {
                    "day_name": "Mon",
                    "high_f": 70,
                    "low_f": 50,
                    "condition": "Sunny",
                    "precip_chance": 0,
                    "precip_type": "none",
                }
            ]
        }
        html = _build_chart_html(weather)
        assert "Sunny" in html

    def test_humidity_rounded_in_header(self):
        """Non-integer humidity should render as rounded integer."""
        weather = {
            "city": "Logan",
            "state": "UT",
            "humidity": 86.601412091818,
        }
        html = _build_header_html(weather)
        assert "Humidity 87%" in html
        assert "86.6" not in html


class TestBuildLegendHtml:
    """AQI band legend shown above the chart."""

    def test_shown_when_aqi_strip_true(self):
        html = _build_legend_html(True)
        assert "BANDS" in html
        assert "Good" in html
        assert "Moderate" in html
        assert "USG" in html
        assert "Unhealthy" in html

    def test_hidden_when_aqi_strip_false(self):
        assert _build_legend_html(False) == ""

    def test_uses_readable_colors(self):
        """Legend swatches use the darker readable variants, not bright EPA."""
        html = _build_legend_html(True)
        assert "#15803d" in html   # Good (dark green)
        assert "#854d0e" in html   # Moderate (amber)
        # Bright EPA yellow (#ffff00) would be invisible on white — don't use it.
        assert "#ffff00" not in html

    def test_normal_and_record_legend_entries(self):
        html = _build_legend_html(False, show_normal=True, show_record=True)
        assert "Normal marker" in html
        assert "Record marker" in html


class TestNormalRecordOverlayOnBar:
    """Normal and record markers drawn with Gmail-safe spacer tables."""

    def test_normal_and_record_markers_render_by_default(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather)
        assert "wx-normal-band" in html
        assert "wx-record-band" in html

    def test_normal_and_record_markers_do_not_render_as_ranges(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather)
        assert "height:2px" not in html

    def test_normal_and_record_bands_can_be_suppressed(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_normal=False, show_record=False)
        assert "wx-normal-band" not in html
        assert "wx-record-band" not in html

    def test_missing_normal_record_values_do_not_render_empty_bands(self):
        weather = {
            "forecast": [
                {
                    "date": "2026-04-08",
                    "day_name": "Mon",
                    "high_f": 70,
                    "low_f": 50,
                    "condition": "Clear",
                }
            ]
        }
        html = _build_chart_html(weather)
        assert "wx-normal-band" not in html
        assert "wx-record-band" not in html


class TestAqiOverlayOnBar:
    """Per-day AQI number drawn on top of the temp bar.

    Restored after earlier position:absolute approach was stripped by Gmail.
    Uses a td with width:{aqi_pct}% as a spacer so the number lands near its
    mark on the 0..AQI_SCALE_MAX scale.
    """

    def test_all_aqi_numbers_render_on_bars(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_aqi=True)
        for entry in weather["aqi_forecast"].values():
            # The number appears inside a <td>…</td>, so look for >N<.
            assert f">{entry['aqi']}<" in html

    def test_overlay_suppressed_when_show_aqi_false(self):
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_aqi=False)
        for entry in weather["aqi_forecast"].values():
            assert f">{entry['aqi']}<" not in html

    def test_overlay_uses_aqi_color(self):
        """Each AQI number should be wrapped in a span with its band color."""
        weather = _load_fixture("weather_clear.json")
        html = _build_chart_html(weather, show_aqi=True)
        # All fixture AQI values are in the Good band (≤50) → dark green.
        assert "#15803d" in html

    def test_no_overlay_when_aqi_forecast_missing(self):
        """Fixture without aqi_forecast should render chart but no AQI row."""
        weather = _load_fixture("weather_missing_aqi.json")
        html = _build_chart_html(weather, show_aqi=True)
        assert "<table" in html

    def test_high_aqi_right_aligns_to_stay_in_bar(self):
        """AQI values ≥ 85% of AQI_SCALE_MAX get right-aligned so the label
        doesn't overflow the bar's right edge."""
        weather = {
            "forecast": [
                {
                    "date": "2026-04-08",
                    "day_name": "Mon",
                    "high_f": 70,
                    "low_f": 50,
                    "condition": "Hazy",
                }
            ],
            "aqi_forecast": {
                "2026-04-08": {"aqi": 180, "aqi_label": "Unhealthy"}
            },
        }
        html = _build_chart_html(weather, show_aqi=True)
        assert "180" in html
        assert "text-align:right" in html

    def test_aqi_scale_max_is_200(self):
        """Contract: scale ceiling matches the top of EPA's Unhealthy band."""
        assert AQI_SCALE_MAX == 200
