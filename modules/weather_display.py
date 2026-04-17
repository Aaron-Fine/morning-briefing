"""Weather display module — HTML table chart for email embedding.

Public API:
    render_weather_html(weather: dict, config: dict) -> str

Returns a complete HTML block (header + chart) for embedding in the Morning
Digest email. Uses only <table>/<div>/<span> with inline styles so the output
survives Gmail's HTML sanitiser.

The chart renders:
  - a header row: location · current conditions · AQI · wind · humidity
  - a 7-day grid where each row shows day name, low temp, a hi→lo gradient
    range bar, high temp, and a right column with condition + precip chance.
  - a thin blue precip underline when the day has measurable precip.

Normal / record / AQI-on-bar overlays were part of an earlier design that
relied on absolute-positioned children (Gmail strips `position:relative` on
divs, breaking them). The current chart intentionally has no overlays, so
there is no legend — a legend for things that aren't drawn is worse than no
legend at all.
"""

import logging
from datetime import datetime

log = logging.getLogger(__name__)

# --- Chart layout ---
DAY_COUNT = 7

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
        - render exception → text-only header
    """
    if not weather or not weather.get("forecast"):
        return ""

    try:
        header = _build_header_html(weather)
        chart = _build_chart_html(weather)
        return f"{header}{chart}"
    except Exception as e:
        log.error(f"weather_display: chart render failed: {e}")
        return _build_text_fallback(weather)


def _build_header_html(weather: dict) -> str:
    """Text header with location, current conditions, AQI, wind, humidity."""
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
    humidity_str = f"Humidity {round(humidity)}%" if humidity else ""

    header_parts = [f"{city}, {state} · {temp_str} {condition}"]
    if aqi is not None:
        tc = _aqi_text_color(aqi)
        header_parts.append(
            f'<span style="color:{tc};font-weight:700;">'
            f'AQI {aqi} ({aqi_label})</span>'
        )
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
        f'<div style="font-family:monospace;font-size:13px;'
        f'color:var(--wx-label, #555);'
        f'margin-bottom:4px;display:flex;justify-content:space-between;align-items:baseline;">'
        f"<span>{header_text}</span>"
        f'<span style="color:var(--wx-label-dim, #888);font-size:11px;">{date_str}</span>'
        f"</div>"
        f"{aqi_alert}"
    )


def _build_text_fallback(weather: dict) -> str:
    """Simple text fallback when chart rendering fails."""
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


def _build_chart_html(weather: dict) -> str:
    """Build the HTML table chart — horizontal day rows with temp range bars."""
    forecast = weather.get("forecast", [])[:DAY_COUNT]
    if not forecast:
        return ""

    # Scale from hi/lo across the visible forecast, with a small buffer.
    all_temps = [
        t
        for day in forecast
        for t in (day.get("high_f"), day.get("low_f"))
        if t is not None
    ]
    if all_temps:
        temp_min = min(all_temps) - 5
        temp_max = max(all_temps) + 5
    else:
        temp_min, temp_max = 0, 100

    rows = []
    for i, day in enumerate(forecast):
        hi = day.get("high_f")
        lo = day.get("low_f")
        day_name = day.get("day_name", "???")
        condition = day.get("condition", day.get("short_forecast", ""))
        precip_pct = day.get("precip_chance", 0) or 0
        precip_type = day.get("precip_type", "none")
        has_precip = precip_pct > 0 and precip_type != "none"

        lo_pct = _temp_to_pct(lo, temp_min, temp_max) if lo is not None else 0
        hi_pct = _temp_to_pct(hi, temp_min, temp_max) if hi is not None else 100
        bar_width = max(hi_pct - lo_pct, 1)

        # Precip underline (blue/snow-blue bar beneath the temp range)
        precip_bar_html = '<div style="height:3px;"></div>'
        if has_precip:
            p_color = _precip_color(precip_type)
            opacity = 0.5 + (precip_pct / 100.0) * 0.3
            precip_bar_html = (
                f'<div style="position:relative;height:3px;'
                f'background:#d8d5d0;border-radius:2px;">'
                f'<div style="position:absolute;left:0;width:{precip_pct}%;'
                f'height:100%;background:{p_color};opacity:{opacity:.2f};'
                f'border-radius:2px;"></div></div>'
            )

        # Right column: condition always; precip chance appended when present.
        short_cond = _shorten_condition(condition)
        if has_precip:
            p_color = _precip_color(precip_type)
            marker = _precip_marker(precip_type)
            marker_str = f" {marker}" if marker else ""
            bold = " font-weight:600;" if precip_pct >= 40 else ""
            parts = [short_cond] if short_cond else []
            parts.append(
                f'<span style="color:{p_color};{bold}">'
                f'{precip_pct}%{marker_str}</span>'
            )
            right_col = " · ".join(parts)
        else:
            right_col = short_cond

        lo_str = f"{round(lo)}&deg;" if lo is not None else "&mdash;"
        hi_str = f"{round(hi)}&deg;" if hi is not None else "&mdash;"
        border = (
            'border-bottom:1px solid #e5e2dd;'
            if i < len(forecast) - 1
            else ''
        )

        # Temperature row. Bar uses an inner table (3 cells: pre-lo pad, hi-lo
        # gradient, post-hi pad) because Gmail strips `position:relative` from
        # divs, which would break any absolute-positioned child.
        rows.append(
            f'<tr>'
            f'<td style="width:32px;font-size:9px;font-weight:600;'
            f'color:#555555;'
            f'padding:5px 6px 0 0;vertical-align:top;">{day_name.upper()}</td>'
            f'<td style="width:28px;font-size:8px;'
            f'color:#4a6a90;text-align:right;'
            f'padding:6px 5px 0 0;vertical-align:top;">{lo_str}</td>'
            f'<td style="padding:5px 4px 0;vertical-align:top;">'
            f'<table cellspacing="0" cellpadding="0" border="0" '
            f'style="width:100%;border-collapse:collapse;height:14px;'
            f'background:#d8d5d0;border-radius:6px;">'
            f'<tr style="height:14px;">'
            f'<td style="width:{lo_pct:.1f}%;height:14px;padding:0;font-size:0;line-height:0;"></td>'
            f'<td style="width:{bar_width:.1f}%;height:14px;padding:0;font-size:0;line-height:0;'
            f'background:linear-gradient(to right,rgba(90,122,160,0.35),rgba(208,144,80,0.40));'
            f'border-radius:6px;"></td>'
            f'<td style="height:14px;padding:0;font-size:0;line-height:0;"></td>'
            f'</tr>'
            f'</table>'
            f'</td>'
            f'<td style="width:28px;font-size:8px;color:#c07830;'
            f'padding:6px 0 0 5px;vertical-align:top;">{hi_str}</td>'
            f'<td style="width:60px;font-size:9px;'
            f'color:#666666;text-align:right;'
            f'padding:6px 0 0 4px;vertical-align:top;">{right_col}</td>'
            f'</tr>'
        )

        # Precip underline + separator row
        rows.append(
            f'<tr style="{border}">'
            f'<td></td><td></td>'
            f'<td style="padding:1px 4px 5px;">{precip_bar_html}</td>'
            f'<td colspan="2"></td>'
            f'</tr>'
        )

    return (
        '<table cellspacing="0" cellpadding="0" border="0" '
        'style="width:100%;border-collapse:collapse;margin-top:8px;">'
        + "".join(rows)
        + "</table>"
    )


# ====================================================================
# Helpers
# ====================================================================


def _temp_to_pct(temp: float, temp_min: float, temp_max: float) -> float:
    """Map temperature to percentage position (0-100) on the bar. Clamps to bounds."""
    if temp_max == temp_min:
        return 50.0
    pct = (temp - temp_min) / (temp_max - temp_min) * 100.0
    return max(0.0, min(100.0, pct))


def _aqi_text_color(aqi: int | None) -> str:
    """Return a readable text color for AQI inline display.

    The EPA signal colors (#00e400, #ffff00) are illegible on light
    backgrounds, so this returns darker, print-safe variants.
    """
    if aqi is None:
        return "#666666"
    if aqi <= 50:
        return "#15803d"   # Good: dark green
    if aqi <= 100:
        return "#854d0e"   # Moderate: amber
    if aqi <= 150:
        return "#c2410c"   # USG: dark orange
    if aqi <= 200:
        return "#dc2626"   # Unhealthy: red
    if aqi <= 300:
        return "#7c3aed"   # Very Unhealthy: purple
    return "#991b1b"       # Hazardous: dark red


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
