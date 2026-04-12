"""Tests for weather display SVG rendering and helpers."""

import json
import os
import pytest

from modules.weather_display import (
    render_weather_html,
    _build_header_html,
    _build_legend_html,
    _build_text_fallback,
    _precip_marker,
    _shorten_condition,
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


class TestTempToY:
    """Temperature to SVG Y coordinate mapping."""

    def test_higher_temp_lower_y(self):
        """Higher temperatures should map to lower Y values."""
        y_high = _temp_to_y(80, 20, 100)
        y_low = _temp_to_y(20, 20, 100)
        assert y_high < y_low

    def test_midpoint(self):
        """Middle temp should map to middle Y."""
        y = _temp_to_y(60, 20, 100)
        expected = (ZONE2_TOP + ZONE2_BOTTOM) / 2
        assert y == pytest.approx(expected, abs=0.01)

    def test_equal_range(self):
        """When min==max, should return center."""
        y = _temp_to_y(50, 50, 50)
        assert y == (ZONE2_TOP + ZONE2_BOTTOM) / 2

    def test_bounds(self):
        """All Y values should be within zone2 range."""
        for t in [20, 60, 100]:
            y = _temp_to_y(t, 20, 100)
            assert ZONE2_TOP <= y <= ZONE2_BOTTOM


class TestPrecipToHeight:
    """Precipitation probability to bar height mapping."""

    def test_zero_pct(self):
        assert _precip_to_height(0) == 0

    def test_hundred_pct(self):
        assert _precip_to_height(100) == 45

    def test_fifty_pct(self):
        assert _precip_to_height(50) == pytest.approx(22.5)

    def test_custom_max(self):
        assert _precip_to_height(100, max_height=20) == 20


class TestNiceStep:
    """Gridline step calculation."""

    def test_range_100_target_5(self):
        step = _nice_step(0, 100, 5)
        assert step == 20

    def test_range_50_target_5(self):
        step = _nice_step(20, 70, 5)
        assert step == 10

    def test_zero_range(self):
        assert _nice_step(50, 50) == 10

    def test_negative_range(self):
        assert _nice_step(100, 50) > 0


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
        assert "AQI Good" in html

    def test_hide_aqi(self):
        weather = {}
        html = _build_legend_html(weather, show_aqi=False, show_records=True)
        assert "AQI Good" not in html

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
        assert "<svg" in html
        assert "Logan, UT" in html
        assert "AQI 26" in html
        assert "</svg>" in html

    def test_inversion_fixture(self):
        weather = _load_fixture("weather_inversion.json")
        html = render_weather_html(weather, _make_config())
        assert "<svg" in html
        assert "Action Day" in html  # AQI 151-190

    def test_snow_fixture(self):
        weather = _load_fixture("weather_snow.json")
        html = render_weather_html(weather, _make_config())
        assert "<svg" in html
        assert "❄" in html

    def test_thunderstorm_fixture(self):
        weather = _load_fixture("weather_thunderstorm.json")
        html = render_weather_html(weather, _make_config())
        assert "<svg" in html
        assert "⚡" in html

    def test_mixed_fixture(self):
        weather = _load_fixture("weather_mixed.json")
        html = render_weather_html(weather, _make_config())
        assert "<svg" in html
        assert "🌨" in html  # mix marker

    def test_minimal_fixture(self):
        weather = _load_fixture("weather_minimal.json")
        html = render_weather_html(weather, _make_config())
        assert "<svg" in html
        assert "Logan, UT" in html

    def test_missing_aqi_fixture(self):
        weather = _load_fixture("weather_missing_aqi.json")
        html = render_weather_html(weather, _make_config())
        assert "<svg" in html
        assert "--" in html  # missing AQI bars

    def test_svg_contains_gradients(self):
        weather = _load_fixture("weather_clear.json")
        html = render_weather_html(weather, _make_config())
        assert 'id="grad-rain"' in html

    def test_svg_dimensions(self):
        weather = _load_fixture("weather_clear.json")
        html = render_weather_html(weather, _make_config())
        assert f'viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}"' in html

    def test_aqi_strip_disabled(self):
        weather = _load_fixture("weather_clear.json")
        html = render_weather_html(weather, _make_config(aqi_strip=False))
        # AQI strip (Zone 3) should not be in SVG, but header may still mention AQI
        svg_part = html.split("</svg>")[0]
        assert "AQI</text>" not in svg_part  # no AQI strip labels in SVG

    def test_record_band_disabled(self):
        weather = _load_fixture("weather_clear.json")
        html = render_weather_html(weather, _make_config(record_band=False))
        # Should still render normals but not record rects
        assert "<svg" in html

    def test_normal_band_disabled(self):
        weather = _load_fixture("weather_clear.json")
        html = render_weather_html(weather, _make_config(normal_band=False))
        assert "<svg" in html

    def test_exception_falls_back_to_text(self):
        """Force an exception by passing bad data."""
        weather = {"forecast": [{"high_f": "not_a_number"}]}
        html = render_weather_html(weather, _make_config())
        # Should not raise, should return something
        assert isinstance(html, str)


# ---------------------------------------------------------------------------
# New HTML chart helper tests
# ---------------------------------------------------------------------------

from modules.weather_display import (
    _temp_to_pct,
    _aqi_position_pct,
    _aqi_color,
    _precip_color,
)


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
