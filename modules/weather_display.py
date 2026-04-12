"""Weather display module — SVG renderer with adaptive CSS variables.

Public API:
    render_weather_html(weather: dict, config: dict) -> str

Returns a complete HTML block (header + SVG + legend) for embedding
in the Morning Digest email template.
"""

import logging
from datetime import datetime

log = logging.getLogger(__name__)

# --- EPA AQI colors (regulatory, not aesthetic) ---
_AQI_COLORS = {
    "Good": "#00e400",
    "Moderate": "#ffff00",
    "Unhealthy for Sensitive Groups": "#ff7e00",
    "Unhealthy": "#ff0000",
    "Very Unhealthy": "#8f3f97",
    "Hazardous": "#7e0023",
}

_AQI_OPACITIES = {
    "Good": 0.15,
    "Moderate": 0.30,
    "Unhealthy for Sensitive Groups": 0.45,
    "Unhealthy": 0.50,
    "Very Unhealthy": 0.55,
    "Hazardous": 0.60,
}

# --- Chart layout ---
DAY_COUNT = 7
AQI_SCALE_MAX = 200

# --- Precip bar colors by type ---
_PRECIP_COLORS = {
    "snow": "#a0d4f0",
}
_PRECIP_DEFAULT_COLOR = "#5b9bd5"


def render_weather_html(weather: dict, config: dict) -> str:
    """Fetch weather data and return complete HTML block for embedding.

    Fallback chain:
        - empty weather → ""
        - insufficient data → text-only header
        - SVG exception → text-only header
    """
    if not weather or not weather.get("forecast"):
        return ""

    display_config = config.get("weather", {})
    show_aqi = display_config.get("aqi_strip", True)
    show_records = display_config.get("record_band", True)
    show_normals = display_config.get("normal_band", True)

    try:
        header = _build_header_html(weather)
        legend = _build_legend_html(weather, show_aqi, show_records)
        return f"{header}{legend}"
    except Exception as e:
        log.error(f"weather_display: render failed: {e}")
        return _build_text_fallback(weather)


def _build_header_html(weather: dict) -> str:
    """Zone 1: text header with location, current conditions, AQI."""
    city = weather.get("city", "Logan")
    state = weather.get("state", "UT")
    temp = weather.get("current_temp_f")
    condition = weather.get("condition", "")
    aqi = weather.get("aqi")
    aqi_label = weather.get("aqi_label", "")
    wind = weather.get("wind_mph")
    humidity = weather.get("humidity")
    date_str = datetime.now().strftime("%A, %B %d")

    temp_str = f"{temp}°F" if temp is not None else "—°F"
    wind_str = f"Wind {wind} mph" if wind else "Wind calm"
    humidity_str = f"Humidity {humidity}%" if humidity else ""

    header_parts = [f"{city}, {state} · {temp_str} {condition}"]
    if aqi is not None:
        header_parts.append(f"AQI {aqi} ({aqi_label})")
    header_parts.extend([wind_str, humidity_str])
    header_text = " · ".join(p for p in header_parts if p)

    aqi_alert = ""
    if aqi is not None and aqi >= 151:
        if aqi >= 301:
            color = "#7e0023"
            msg = "Maroon Action Day — Hazardous air quality. Everyone should avoid all outdoor activity."
        elif aqi >= 201:
            color = "#8f3f97"
            msg = "Purple Action Day — Very Unhealthy. Avoid prolonged outdoor activity; sensitive groups should stay indoors."
        else:
            color = "#d32f2f"
            msg = "Red Action Day — Unhealthy air quality. Everyone should limit prolonged outdoor activity."
        aqi_alert = f'<span style="color:{color};font-size:13px;font-weight:600;display:block;margin-top:3px;">{msg}</span>'

    return (
        f'<div style="font-family:JetBrains Mono,monospace;font-size:13px;'
        f'color:var(--wx-label, #b0ada8);'
        f'margin-bottom:4px;display:flex;justify-content:space-between;align-items:baseline;">'
        f"<span>{header_text}</span>"
        f'<span style="color:var(--wx-label-dim, #888582);font-size:11px;">{date_str}</span>'
        f"</div>"
        f"{aqi_alert}"
    )


def _build_legend_html(weather: dict, show_aqi: bool, show_records: bool) -> str:
    """Legend row with colored swatches."""
    parts = [
        '<div style="font-size:10px;color:var(--wx-label-dim, #888582);margin-bottom:6px;display:flex;gap:12px;flex-wrap:wrap;">'
    ]

    parts.append(
        '<span style="display:inline-flex;align-items:center;gap:3px;">'
        '<span style="width:8px;height:8px;background:var(--wx-hi, #d09050);border-radius:50%;display:inline-block;"></span>'
        "Forecast Hi</span>"
    )

    parts.append(
        '<span style="display:inline-flex;align-items:center;gap:3px;">'
        '<span style="width:8px;height:1px;border-top:1px dashed var(--wx-lo, #5a7aa0);display:inline-block;"></span>'
        "Forecast Lo</span>"
    )

    parts.append(
        '<span style="display:inline-flex;align-items:center;gap:3px;">'
        '<span style="width:8px;height:8px;background:var(--wx-normal, rgba(100,160,100,0.18));border-radius:1px;display:inline-block;"></span>'
        "Normal</span>"
    )

    if show_records:
        parts.append(
            '<span style="display:inline-flex;align-items:center;gap:3px;">'
            '<span style="width:8px;height:8px;background:var(--wx-record, rgba(255,255,255,0.06));border-radius:1px;display:inline-block;"></span>'
            "Record</span>"
        )

    parts.append(
        '<span style="display:inline-flex;align-items:center;gap:3px;">'
        '<span style="width:8px;height:8px;background:var(--wx-precip, #5b9bd5);border-radius:1px;display:inline-block;"></span>'
        "Precip</span>"
    )

    if show_aqi:
        parts.append(
            '<span style="display:inline-flex;align-items:center;gap:3px;">'
            '<span style="width:8px;height:8px;background:#00e400;border-radius:1px;display:inline-block;"></span>'
            "AQI Good</span>"
        )

    parts.append("</div>")
    return "".join(parts)


def _build_text_fallback(weather: dict) -> str:
    """Simple text fallback when SVG rendering fails."""
    city = weather.get("city", "Logan")
    state = weather.get("state", "UT")
    temp = weather.get("current_temp_f", "—")
    condition = weather.get("condition", "unavailable")
    forecast = weather.get("forecast", [])

    lines = [f"{city}, {state} — {temp}°F {condition}"]
    for day in forecast[:3]:
        hi = day.get("high_f", "—")
        lo = day.get("low_f", "—")
        cond = day.get("condition", "")
        lines.append(f"{day.get('day_name', '')}: {hi}°/{lo}° {cond}")

    return "<p>" + "<br>".join(lines) + "</p>"


# ====================================================================
# Helpers
# ====================================================================


def _temp_to_pct(temp: float, temp_min: float, temp_max: float) -> float:
    """Map temperature to percentage position (0-100) on the bar. Clamps to bounds."""
    if temp_max == temp_min:
        return 50.0
    pct = (temp - temp_min) / (temp_max - temp_min) * 100.0
    return max(0.0, min(100.0, pct))


def _aqi_position_pct(aqi: int) -> float:
    """Map AQI value to percentage on 0-200 scale. Values above 200 pin to 100%."""
    if aqi is None:
        return 0.0
    return min(aqi / AQI_SCALE_MAX * 100.0, 100.0)


def _aqi_color(aqi: int | None) -> str:
    """Return display color for an AQI value using EPA breakpoints."""
    if aqi is None:
        return "#888582"
    if aqi <= 50:
        return "#00e400"
    if aqi <= 100:
        return "#cccc00"
    if aqi <= 150:
        return "#ff7e00"
    if aqi <= 200:
        return "#ff0000"
    if aqi <= 300:
        return "#8f3f97"
    return "#7e0023"


def _precip_color(precip_type: str) -> str:
    """Return bar color for precipitation type."""
    return _PRECIP_COLORS.get(precip_type, _PRECIP_DEFAULT_COLOR)


def _precip_marker(precip_type: str) -> str:
    """Return emoji/text marker for precipitation type."""
    markers = {
        "thunderstorm": "⚡",
        "snow": "❄",
        "mix": "🌨",
        "freezing_rain": "frz",
    }
    return markers.get(precip_type, "")


def _shorten_condition(condition: str) -> str:
    """Shorten condition text for display."""
    if not condition:
        return ""
    condition = condition.lower()
    if "thunderstorm" in condition:
        return "T-storm"
    if "snow" in condition and "rain" in condition:
        return "Mix"
    if "snow" in condition:
        return "Snow"
    if "rain" in condition or "shower" in condition:
        return "Shwrs"
    if "clear" in condition or "sunny" in condition:
        return "Sunny"
    if "cloudy" in condition or "overcast" in condition:
        return "Cloudy"
    if "fog" in condition:
        return "Fog"
    # Truncate long conditions
    if len(condition) > 15:
        return condition[:12] + "..."
    return condition.capitalize()
