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


def _build_chart_html(
    weather: dict, show_records: bool, show_normals: bool
) -> str:
    """Build the HTML table chart — horizontal day rows with temp range bars."""
    forecast = weather.get("forecast", [])[:DAY_COUNT]
    normals = weather.get("normals", [])
    aqi_forecast = weather.get("aqi_forecast", {})

    if not forecast:
        return ""

    # Determine temperature scale from all data points
    all_temps = []
    for day in forecast:
        if day.get("high_f") is not None:
            all_temps.append(day["high_f"])
        if day.get("low_f") is not None:
            all_temps.append(day["low_f"])
    for nr in normals:
        if show_records:
            if nr.get("record_hi") is not None:
                all_temps.append(nr["record_hi"])
            if nr.get("record_lo") is not None:
                all_temps.append(nr["record_lo"])
        if show_normals:
            if nr.get("normal_hi") is not None:
                all_temps.append(nr["normal_hi"])
            if nr.get("normal_lo") is not None:
                all_temps.append(nr["normal_lo"])

    if not all_temps:
        temp_min, temp_max = 0, 100
    else:
        temp_min = min(all_temps) - 5
        temp_max = max(all_temps) + 5

    rows = []
    for i, day in enumerate(forecast):
        hi = day.get("high_f")
        lo = day.get("low_f")
        day_name = day.get("day_name", "???")
        date_str = day.get("date", "")
        condition = day.get("condition", day.get("short_forecast", ""))
        precip_pct = day.get("precip_chance", 0) or 0
        precip_type = day.get("precip_type", "none")

        # Temperature bar positions
        lo_pct = _temp_to_pct(lo, temp_min, temp_max) if lo is not None else 0
        hi_pct = _temp_to_pct(hi, temp_min, temp_max) if hi is not None else 100
        bar_width = max(hi_pct - lo_pct, 1)

        # Normal ticks
        normal_lo_tick = ""
        normal_hi_tick = ""
        if show_normals and i < len(normals):
            nr = normals[i]
            if nr.get("normal_lo") is not None:
                nlo_pct = _temp_to_pct(nr["normal_lo"], temp_min, temp_max)
                normal_lo_tick = (
                    f'<div style="position:absolute;left:{nlo_pct:.1f}%;top:0;'
                    f'width:2px;height:100%;background:rgba(100,160,100,0.45);'
                    f'border-radius:1px;"></div>'
                )
            if nr.get("normal_hi") is not None:
                nhi_pct = _temp_to_pct(nr["normal_hi"], temp_min, temp_max)
                normal_hi_tick = (
                    f'<div style="position:absolute;left:{nhi_pct:.1f}%;top:0;'
                    f'width:2px;height:100%;background:rgba(100,160,100,0.45);'
                    f'border-radius:1px;"></div>'
                )

        # Record ticks
        record_lo_tick = ""
        record_hi_tick = ""
        if show_records and i < len(normals):
            nr = normals[i]
            if nr.get("record_lo") is not None:
                rlo_pct = _temp_to_pct(nr["record_lo"], temp_min, temp_max)
                record_lo_tick = (
                    f'<div style="position:absolute;left:{rlo_pct:.1f}%;top:0;'
                    f'width:2px;height:100%;background:rgba(211,47,47,0.35);'
                    f'border-radius:1px;"></div>'
                )
            if nr.get("record_hi") is not None:
                rhi_pct = _temp_to_pct(nr["record_hi"], temp_min, temp_max)
                record_hi_tick = (
                    f'<div style="position:absolute;left:{rhi_pct:.1f}%;top:0;'
                    f'width:2px;height:100%;background:rgba(211,47,47,0.35);'
                    f'border-radius:1px;"></div>'
                )

        # AQI number on bar
        aqi_data = aqi_forecast.get(date_str, {})
        aqi_val = aqi_data.get("aqi")
        aqi_html = ""
        if aqi_val is not None:
            aqi_pct = _aqi_position_pct(aqi_val)
            color = _aqi_color(aqi_val)
            if aqi_val > AQI_SCALE_MAX:
                # Pin to right edge
                aqi_html = (
                    f'<div style="position:absolute;right:2px;top:0;height:100%;'
                    f'display:flex;align-items:center;">'
                    f'<span style="font-size:7px;color:{color};font-weight:600;">'
                    f'{aqi_val}</span></div>'
                )
            else:
                aqi_html = (
                    f'<div style="position:absolute;left:{aqi_pct:.1f}%;top:0;'
                    f'height:100%;display:flex;align-items:center;">'
                    f'<span style="font-size:7px;color:{color};font-weight:600;'
                    f'margin-left:-6px;">{aqi_val}</span></div>'
                )

        # Precip underline bar
        precip_bar_html = ""
        if precip_pct > 0 and precip_type != "none":
            p_color = _precip_color(precip_type)
            opacity = 0.5 + (precip_pct / 100.0) * 0.3
            precip_bar_html = (
                f'<div style="position:relative;height:3px;background:#1e1e1e;'
                f'border-radius:2px;">'
                f'<div style="position:absolute;left:0;width:{precip_pct}%;'
                f'height:100%;background:{p_color};opacity:{opacity:.2f};'
                f'border-radius:2px;"></div></div>'
            )

        # Condition/precip right column
        short_cond = _shorten_condition(condition)
        marker = _precip_marker(precip_type)
        if precip_pct > 0 and precip_type != "none":
            p_color = _precip_color(precip_type)
            bold = " font-weight:600;" if precip_pct >= 40 else ""
            marker_str = f" {marker}" if marker else ""
            right_col = (
                f'<span style="color:{p_color};{bold}">'
                f'{precip_pct}%</span>{marker_str}'
            )
        else:
            right_col = short_cond

        lo_str = f"{round(lo)}&deg;" if lo is not None else "&mdash;"
        hi_str = f"{round(hi)}&deg;" if hi is not None else "&mdash;"
        border = 'border-bottom:1px solid #2a2a2a;' if i < len(forecast) - 1 else ''

        # Temperature row
        rows.append(
            f'<tr>'
            f'<td style="width:32px;font-size:9px;font-weight:600;color:#b0ada8;'
            f'padding:5px 6px 0 0;vertical-align:top;">{day_name.upper()}</td>'
            f'<td style="width:28px;font-size:8px;color:#5a7aa0;text-align:right;'
            f'padding:6px 5px 0 0;vertical-align:top;">{lo_str}</td>'
            f'<td style="padding:5px 4px 0;vertical-align:top;">'
            f'<div style="position:relative;height:14px;background:#252525;'
            f'border-radius:6px;">'
            f'{record_lo_tick}{record_hi_tick}'
            f'{normal_lo_tick}{normal_hi_tick}'
            f'<div style="position:absolute;left:{lo_pct:.1f}%;'
            f'width:{bar_width:.1f}%;height:100%;background:linear-gradient('
            f'to right,rgba(90,122,160,0.35),rgba(208,144,80,0.40));'
            f'border-radius:6px;"></div>'
            f'{aqi_html}'
            f'</div>'
            f'</td>'
            f'<td style="width:28px;font-size:8px;color:#d09050;'
            f'padding:6px 0 0 5px;vertical-align:top;">{hi_str}</td>'
            f'<td style="width:50px;font-size:7px;color:#888582;text-align:right;'
            f'padding:6px 0 0 4px;vertical-align:top;">{right_col}</td>'
            f'</tr>'
        )

        # Precip underline + separator row
        rows.append(
            f'<tr style="{border}">'
            f'<td></td><td></td>'
            f'<td style="padding:1px 4px 5px;">'
            f'{precip_bar_html if precip_bar_html else "<div style=\"height:3px;\"></div>"}'
            f'</td>'
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
