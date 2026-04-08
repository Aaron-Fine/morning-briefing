"""Stage: prepare_weather — deterministic, no LLM.

Promotes weather data from raw_sources into a dedicated artifact so downstream
stages and the assembler can consume it independently.  Also renders the SVG
weather display for the email template.

Input:  context["raw_sources"]["weather"]
Output: {"weather": <weather dict>, "weather_html": <HTML string>}
"""

import logging

from modules.weather_display import render_weather_html

log = logging.getLogger(__name__)


def run(
    context: dict, config: dict, model_config: dict | None = None, **kwargs
) -> dict:
    raw = context.get("raw_sources", {})
    weather = raw.get("weather", {})
    if not weather:
        log.warning("prepare_weather: no weather data in raw_sources")
        return {"weather": {}, "weather_html": ""}

    city = weather.get("city", "?")
    temp = weather.get("current_temp_f")
    cond = weather.get("condition", "")
    log.info(f"prepare_weather: {city} — {temp}°F, {cond}")

    weather_html = render_weather_html(weather, config)
    return {"weather": weather, "weather_html": weather_html}
