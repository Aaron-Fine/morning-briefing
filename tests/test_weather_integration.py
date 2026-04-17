"""Integration tests for weather pipeline: prepare_weather → assemble."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from stages.prepare_weather import run as run_prepare_weather
from modules.weather_display import render_weather_html

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return json.load(f)


def _make_config(**overrides):
    config = {
        "location": {
            "city": "Logan",
            "state": "UT",
            "latitude": 41.737,
            "longitude": -111.834,
            "timezone": "America/Denver",
        },
        "weather": {
            "aqi_strip": True,
            "record_band": True,
            "normal_band": True,
            "nws_station": "KLGU",
        },
        "digest": {
            "at_a_glance": {"max_items": 14, "normal_items": 10},
            "deep_dives": {"count": 2},
        },
    }
    config["weather"].update(overrides)
    return config


class TestPrepareWeatherStage:
    """Tests for stages/prepare_weather.py."""

    def test_returns_weather_and_html(self):
        weather = _load_fixture("weather_clear.json")
        config = _make_config()
        context = {"raw_sources": {"weather": weather}}
        result = run_prepare_weather(context, config)
        assert "weather" in result
        assert "weather_html" in result
        assert result["weather"] == weather
        assert "<table" in result["weather_html"]

    def test_empty_weather_returns_empty(self):
        config = _make_config()
        context = {"raw_sources": {"weather": {}}}
        result = run_prepare_weather(context, config)
        assert result["weather"] == {}
        assert result["weather_html"] == ""

    def test_no_raw_sources(self):
        config = _make_config()
        context = {}
        result = run_prepare_weather(context, config)
        assert result["weather"] == {}
        assert result["weather_html"] == ""

    def test_all_fixtures_produce_html(self):
        """Every fixture should produce valid HTML table output."""
        fixtures = [
            "weather_clear.json",
            "weather_inversion.json",
            "weather_snow.json",
            "weather_thunderstorm.json",
            "weather_mixed.json",
            "weather_minimal.json",
            "weather_missing_aqi.json",
        ]
        config = _make_config()
        for fname in fixtures:
            weather = _load_fixture(fname)
            context = {"raw_sources": {"weather": weather}}
            result = run_prepare_weather(context, config)
            assert "<table" in result["weather_html"], f"Failed for {fname}"


class TestRenderWeatherHtmlIntegration:
    """End-to-end rendering tests with all fixtures."""

    def test_clear_skies_has_all_sections(self):
        weather = _load_fixture("weather_clear.json")
        config = _make_config()
        html = render_weather_html(weather, config)
        assert "Logan, UT" in html  # header
        assert "<table" in html  # chart
        assert "AQI" in html  # legend/AQI numbers

    def test_inversion_has_aqi_alert(self):
        weather = _load_fixture("weather_inversion.json")
        config = _make_config()
        html = render_weather_html(weather, config)
        assert "Action Day" in html
        assert "Unhealthy" in html

    def test_snow_has_snow_marker(self):
        weather = _load_fixture("weather_snow.json")
        config = _make_config()
        html = render_weather_html(weather, config)
        assert "❄" in html

    def test_thunderstorm_has_lightning_marker(self):
        weather = _load_fixture("weather_thunderstorm.json")
        config = _make_config()
        html = render_weather_html(weather, config)
        assert "⚡" in html

    def test_mixed_has_mix_marker(self):
        weather = _load_fixture("weather_mixed.json")
        config = _make_config()
        html = render_weather_html(weather, config)
        assert "🌨" in html

    def test_minimal_handles_missing_aqi(self):
        weather = _load_fixture("weather_minimal.json")
        config = _make_config()
        html = render_weather_html(weather, config)
        assert "<table" in html
        assert "Logan, UT" in html

    def test_missing_aqi_renders(self):
        weather = _load_fixture("weather_missing_aqi.json")
        config = _make_config()
        html = render_weather_html(weather, config)
        assert "<table" in html

    def test_day_labels_present(self):
        weather = _load_fixture("weather_clear.json")
        config = _make_config()
        html = render_weather_html(weather, config)
        # Derive expected day labels from fixture data (uppercase)
        expected_days = [day["day_name"].upper() for day in weather["forecast"]]
        for day in expected_days:
            assert day in html, f"Missing day label: {day}"

    def test_precip_chance_labels(self):
        weather = _load_fixture("weather_clear.json")
        config = _make_config()
        html = render_weather_html(weather, config)
        assert "%" in html  # precipitation chance labels

    def test_no_svg_in_output(self):
        weather = _load_fixture("weather_clear.json")
        config = _make_config()
        html = render_weather_html(weather, config)
        assert "<svg" not in html
        assert "viewBox" not in html

    def test_header_date_format(self):
        weather = _load_fixture("weather_clear.json")
        config = _make_config()
        html = render_weather_html(weather, config)
        # Should contain current day name
        from datetime import datetime

        today_name = datetime.now().strftime("%A")
        assert today_name in html

    def test_band_flags_accepted(self):
        """aqi_strip/record_band/normal_band config flags are accepted but no
        longer gate any rendered overlays — kept so existing config.yaml
        entries don't error."""
        weather = _load_fixture("weather_clear.json")
        config = _make_config(
            aqi_strip=False, record_band=False, normal_band=False
        )
        html = render_weather_html(weather, config)
        assert "<table" in html

    def test_fallback_on_exception(self):
        """Force exception path by passing malformed data."""
        weather = {"forecast": [{"high_f": None, "low_f": None}]}
        config = _make_config()
        html = render_weather_html(weather, config)
        assert isinstance(html, str)
        assert len(html) > 0

    def test_max_7_days(self):
        """Ensure only 7 days are rendered even if more provided."""
        weather = _load_fixture("weather_clear.json")
        # Add extra days with unique marker that won't appear elsewhere in HTML
        extra_day_marker = "EXTRA"
        for i in range(3):
            weather["forecast"].append(
                {
                    "date": f"2026-04-{15 + i:02d}",
                    "day_name": extra_day_marker,
                    "high_f": 70,
                    "low_f": 50,
                    "precip_chance": 0,
                    "condition": "Clear",
                    "short_forecast": "Clear",
                    "detailed_forecast": "Clear.",
                    "precip_type": "none",
                    "precip_timing": "",
                }
            )
        weather["normals"].extend(
            [
                {
                    "date": f"2026-04-{15 + i:02d}",
                    "normal_hi": 52,
                    "normal_lo": 34,
                    "record_hi": 84,
                    "record_lo": 15,
                }
                for i in range(3)
            ]
        )
        config = _make_config()
        html = render_weather_html(weather, config)
        # Count occurrences of unique marker - should be 0 (extra days not rendered)
        marker_count = html.count(extra_day_marker.upper())
        assert marker_count == 0, f"Found {marker_count} extra day markers in HTML"
