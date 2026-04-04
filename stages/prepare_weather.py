"""Stage: prepare_weather — deterministic, no LLM.

Promotes weather data from raw_sources into a dedicated artifact so downstream
stages and the assembler can consume it independently.

Input:  context["raw_sources"]["weather"]
Output: {"weather": <weather dict>}
"""

import logging

log = logging.getLogger(__name__)


def run(context: dict, config: dict, model_config, **kwargs) -> dict:
    raw = context.get("raw_sources", {})
    weather = raw.get("weather", {})
    if not weather:
        log.warning("prepare_weather: no weather data in raw_sources")
    else:
        city = weather.get("city", "?")
        temp = weather.get("current_temp_f")
        cond = weather.get("condition", "")
        log.info(f"prepare_weather: {city} — {temp}°F, {cond}")
    return {"weather": weather}
