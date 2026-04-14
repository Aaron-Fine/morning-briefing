"""Weather display module — HTML table chart for email embedding.

Public API:
    render_weather_html(weather: dict, config: dict) -> str

Returns a complete HTML block (header + legend + chart) for embedding
in the Morning Digest email template.  Uses only <table>/<div>/<span>
with inline styles so the output survives Gmail's HTML sanitiser.
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
        chart = _build_chart_html(weather, show_records, show_normals)
        header = _build_header_html(weather)
        legend = _build_legend_html(weather, show_aqi, show_records)
        return f"{header}{legend}{chart}"
    except Exception as e:
        log.error(f"weather_display: chart render failed: {e}")
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
        f'color:var(--wx-label, #555);'
        f'margin-bottom:4px;display:flex;justify-content:space-between;align-items:baseline;">'
        f"<span>{header_text}</span>"
        f'<span style="color:var(--wx-label-dim, #888);font-size:11px;">{date_str}</span>'
        f"</div>"
        f"{aqi_alert}"
    )


def _build_legend_html(weather: dict, show_aqi: bool, show_records: bool) -> str:
    """Legend row with colored swatches."""
    items = [
        _legend_item(
            '<span style="width:8px;height:8px;background:var(--wx-hi, #c07830);'
            'border-radius:50%;display:inline-block;"></span>',
            "Forecast Hi",
        ),
        _legend_item(
            '<span style="width:8px;height:1px;'
            'border-top:1px dashed var(--wx-lo, #4a6a90);'
            'display:inline-block;"></span>',
            "Forecast Lo",
        ),
        _legend_item(
            '<span style="width:2px;height:10px;'
            'background:var(--wx-normal, rgba(80,140,80,0.45));'
            'border-radius:1px;display:inline-block;"></span>',
            "Normal",
        ),
    ]
    if show_records:
        items.append(
            _legend_item(
                '<span style="width:2px;height:10px;'
                'background:var(--wx-record, rgba(192,57,43,0.35));'
                'border-radius:1px;display:inline-block;"></span>',
                "Record",
            )
        )
    items.append(
        _legend_item(
            '<span style="width:8px;height:3px;'
            'background:var(--wx-precip, #5b9bd5);'
            'border-radius:1px;display:inline-block;"></span>',
            "Precip",
        )
    )
    if show_aqi:
        aqi_swatch = (
            "AQI "
            '<span style="color:#00e400;font-weight:600;font-size:8px;">##</span>'
            '<span style="color:#cccc00;font-weight:600;font-size:8px;">##</span>'
            '<span style="color:#ff0000;font-weight:600;font-size:8px;">##</span>'
        )
        items.append(_legend_item(aqi_swatch, " on bar"))

    return (
        '<div style="font-size:10px;color:var(--wx-label-dim, #888);'
        'margin-bottom:6px;display:flex;gap:12px;flex-wrap:wrap;">'
        + "".join(items)
        + "</div>"
    )


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

        # Precip underline bar
        precip_bar_html = ""
        if precip_pct > 0 and precip_type != "none":
            p_color = _precip_color(precip_type)
            opacity = 0.5 + (precip_pct / 100.0) * 0.3
            precip_bar_html = (
                f'<div style="position:relative;height:3px;'
                f'background:#d8d5d0;'
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
        border = (
            'border-bottom:1px solid #e5e2dd;'
            if i < len(forecast) - 1
            else ''
        )

        # Temperature row — bar uses inner table so position:absolute is not needed
        # (Gmail strips position:relative from divs, breaking absolute-child offsets)
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
            f'<td style="width:50px;font-size:7px;'
            f'color:#888888;text-align:right;'
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


def _legend_item(swatch_html: str, label: str) -> str:
    """Wrap a legend swatch + label in the standard inline-flex span."""
    return (
        f'<span style="display:inline-flex;align-items:center;gap:3px;">'
        f"{swatch_html}{label}</span>"
    )


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
