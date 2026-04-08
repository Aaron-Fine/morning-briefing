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

# --- Precip gradient definitions ---
_PRECIP_GRADIENTS = {
    "rain": ("#5b9bd5", "rgba(91,155,213,0.2)"),
    "thunderstorm": ("#5b9bd5", "#8f3f97", "#c8a44a"),
    "snow": ("#a0d4f0", "rgba(160,212,240,0.3)"),
    "mix": ("#5b9bd5", "#a0d4f0"),
    "freezing_rain": ("#5b9bd5", "#e06040"),
}

# --- SVG dimensions ---
SVG_WIDTH = 640
SVG_HEIGHT = 230
ZONE2_TOP = 8
ZONE2_BOTTOM = 128
ZONE3_Y = 133
ZONE3_HEIGHT = 10
ZONE4_BASELINE = 190
ZONE4_MAX_HEIGHT = 45
ZONE5_Y = 194
DAY_COUNT = 7
DAY_SPACING = (SVG_WIDTH - 60) / DAY_COUNT  # 60px left margin for labels
DAY_START_X = 50


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
        svg = _build_svg(weather, show_aqi, show_records, show_normals)
        header = _build_header_html(weather)
        legend = _build_legend_html(weather, show_aqi, show_records)
        return f"{header}{legend}{svg}"
    except Exception as e:
        log.error(f"weather_display: SVG render failed: {e}")
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
        f'<div style="font-family:JetBrains Mono,monospace;font-size:13px;color:#ccc;'
        f'margin-bottom:4px;display:flex;justify-content:space-between;align-items:baseline;">'
        f"<span>{header_text}</span>"
        f'<span style="color:#888;font-size:11px;">{date_str}</span>'
        f"</div>"
        f"{aqi_alert}"
    )


def _build_legend_html(weather: dict, show_aqi: bool, show_records: bool) -> str:
    """Legend row with colored swatches."""
    parts = [
        '<div style="font-size:10px;color:#888;margin-bottom:6px;display:flex;gap:12px;flex-wrap:wrap;">'
    ]

    parts.append(
        '<span style="display:inline-flex;align-items:center;gap:3px;">'
        '<span style="width:8px;height:8px;background:#d09050;border-radius:50%;display:inline-block;"></span>'
        "Forecast Hi</span>"
    )

    parts.append(
        '<span style="display:inline-flex;align-items:center;gap:3px;">'
        '<span style="width:8px;height:1px;border-top:1px dashed #5a7aa0;display:inline-block;"></span>'
        "Forecast Lo</span>"
    )

    parts.append(
        '<span style="display:inline-flex;align-items:center;gap:3px;">'
        '<span style="width:8px;height:8px;background:rgba(100,160,100,0.18);border-radius:1px;display:inline-block;"></span>'
        "Normal</span>"
    )

    if show_records:
        parts.append(
            '<span style="display:inline-flex;align-items:center;gap:3px;">'
            '<span style="width:8px;height:8px;background:rgba(255,255,255,0.04);border-radius:1px;display:inline-block;"></span>'
            "Record</span>"
        )

    parts.append(
        '<span style="display:inline-flex;align-items:center;gap:3px;">'
        '<span style="width:8px;height:8px;background:#5b9bd5;border-radius:1px;display:inline-block;"></span>'
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


def _build_svg(
    weather: dict, show_aqi: bool, show_records: bool, show_normals: bool
) -> str:
    """Build the complete SVG display."""
    forecast = weather.get("forecast", [])[:DAY_COUNT]
    aqi_forecast = weather.get("aqi_forecast", {})
    normals = weather.get("normals", [])

    # Determine temperature range for Y-axis
    all_temps = []
    for day in forecast:
        if day.get("high_f") is not None:
            all_temps.append(day["high_f"])
        if day.get("low_f") is not None:
            all_temps.append(day["low_f"])
    for nr in normals:
        if show_records:
            all_temps.append(nr.get("record_hi", 0))
            all_temps.append(nr.get("record_lo", 0))
        if show_normals:
            all_temps.append(nr.get("normal_hi", 0))
            all_temps.append(nr.get("normal_lo", 0))

    if not all_temps:
        temp_min, temp_max = 0, 100
    else:
        temp_min = min(all_temps) - 5
        temp_max = max(all_temps) + 5

    # Build SVG sections
    defs = _render_defs()
    gridlines = _render_zone2_gridlines(temp_min, temp_max)
    bands = _render_zone2_bands(
        forecast, normals, temp_min, temp_max, show_records, show_normals
    )
    lines = _render_zone2_lines(forecast, normals, temp_min, temp_max)
    aqi_strip = _render_zone3_aqi(forecast, aqi_forecast) if show_aqi else ""
    precip_bars = _render_zone4_precip(forecast)
    day_labels = _render_zone5_labels(forecast)

    return (
        f'<svg viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;max-width:{SVG_WIDTH}px;font-family:JetBrains Mono,monospace;">'
        f"{defs}"
        f"{gridlines}"
        f"{bands}"
        f"{lines}"
        f"{aqi_strip}"
        f"{precip_bars}"
        f"{day_labels}"
        f"</svg>"
    )


def _render_defs() -> str:
    """SVG <defs> with linear gradients for precipitation types."""
    gradients = []
    for ptype, colors in _PRECIP_GRADIENTS.items():
        if len(colors) == 2:
            c1, c2 = colors
            gradients.append(
                f'<linearGradient id="grad-{ptype}" x1="0" y1="1" x2="0" y2="0">'
                f'<stop offset="0%" stop-color="{c1}"/>'
                f'<stop offset="100%" stop-color="{c2}"/>'
                f"</linearGradient>"
            )
        elif len(colors) == 3:
            c1, c2, stroke = colors
            gradients.append(
                f'<linearGradient id="grad-{ptype}" x1="0" y1="1" x2="0" y2="0">'
                f'<stop offset="0%" stop-color="{c1}"/>'
                f'<stop offset="50%" stop-color="{c2}"/>'
                f'<stop offset="100%" stop-color="{c1}"/>'
                f"</linearGradient>"
            )
    return "<defs>" + "".join(gradients) + "</defs>"


def _render_zone2_gridlines(temp_min: float, temp_max: float) -> str:
    """Horizontal gridlines with Y-axis temperature labels."""
    lines = []
    step = _nice_step(temp_min, temp_max, target_lines=5)
    start = int(temp_min / step) * step
    end = int(temp_max / step) * step + step

    for t in range(int(start), int(end) + 1, int(step)):
        y = _temp_to_y(t, temp_min, temp_max)
        if ZONE2_TOP <= y <= ZONE2_BOTTOM:
            lines.append(
                f'<line x1="40" y1="{y}" x2="{SVG_WIDTH - 10}" y2="{y}" '
                f'stroke="#1e1e22" stroke-width="0.5"/>'
                f'<text x="35" y="{y + 3}" text-anchor="end" '
                f'font-size="7" fill="#555">{t}°</text>'
            )

    return "".join(lines)


def _render_zone2_bands(
    forecast: list,
    normals: list,
    temp_min: float,
    temp_max: float,
    show_records: bool,
    show_normals: bool,
) -> str:
    """Background bands: record range, normal range, forecast fill."""
    bands = []
    for i, day in enumerate(forecast):
        x = DAY_START_X + i * DAY_SPACING
        w = DAY_SPACING * 0.8

        if show_records and i < len(normals):
            nr = normals[i]
            rec_hi = nr.get("record_hi", temp_max)
            rec_lo = nr.get("record_lo", temp_min)
            y_hi = _temp_to_y(rec_hi, temp_min, temp_max)
            y_lo = _temp_to_y(rec_lo, temp_min, temp_max)
            bands.append(
                f'<rect x="{x}" y="{y_hi}" width="{w}" height="{y_lo - y_hi}" '
                f'fill="rgba(255,255,255,0.02)" rx="1"/>'
            )

        if show_normals and i < len(normals):
            nr = normals[i]
            norm_hi = nr.get("normal_hi", 0)
            norm_lo = nr.get("normal_lo", 0)
            y_hi = _temp_to_y(norm_hi, temp_min, temp_max)
            y_lo = _temp_to_y(norm_lo, temp_min, temp_max)
            bands.append(
                f'<rect x="{x}" y="{y_hi}" width="{w}" height="{y_lo - y_hi}" '
                f'fill="rgba(100,160,100,0.12)" rx="1"/>'
            )

        # Forecast band (between high and low)
        hi = day.get("high_f")
        lo = day.get("low_f")
        if hi is not None and lo is not None:
            y_hi = _temp_to_y(hi, temp_min, temp_max)
            y_lo = _temp_to_y(lo, temp_min, temp_max)
            bands.append(
                f'<rect x="{x}" y="{y_hi}" width="{w}" height="{y_lo - y_hi}" '
                f'fill="rgba(208,144,80,0.08)" rx="2"/>'
            )

    return "".join(bands)


def _render_zone2_lines(
    forecast: list,
    normals: list,
    temp_min: float,
    temp_max: float,
) -> str:
    """High line (solid amber) and low line (dashed blue) with dots and labels."""
    elements = []
    high_points = []
    low_points = []

    for i, day in enumerate(forecast):
        x = DAY_START_X + i * DAY_SPACING + DAY_SPACING / 2
        hi = day.get("high_f")
        lo = day.get("low_f")

        if hi is not None:
            y = _temp_to_y(hi, temp_min, temp_max)
            high_points.append((x, y, hi))

        if lo is not None:
            y = _temp_to_y(lo, temp_min, temp_max)
            low_points.append((x, y, lo))

    # High line
    if len(high_points) >= 2:
        path_d = " ".join(
            f"M{p[0]},{p[1]}" if idx == 0 else f"L{p[0]},{p[1]}"
            for idx, p in enumerate(high_points)
        )
        elements.append(
            f'<path d="{path_d}" fill="none" stroke="#d09050" stroke-width="2"/>'
        )

    # Low line
    if len(low_points) >= 2:
        path_d = " ".join(
            f"M{p[0]},{p[1]}" if idx == 0 else f"L{p[0]},{p[1]}"
            for idx, p in enumerate(low_points)
        )
        elements.append(
            f'<path d="{path_d}" fill="none" stroke="#5a7aa0" stroke-width="1.5" '
            f'stroke-dasharray="4,2"/>'
        )

    # Dots and labels
    for x, y, temp in high_points:
        # Check if near record
        near_record = False
        for i, day in enumerate(forecast):
            day_x = DAY_START_X + i * DAY_SPACING + DAY_SPACING / 2
            if abs(day_x - x) < 1 and i < len(normals):
                nr = normals[i]
                if abs(temp - nr.get("record_hi", 999)) <= 2:
                    near_record = True
                    break

        r = 4 if near_record else 2.5
        elements.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#d09050"/>')
        elements.append(
            f'<text x="{x}" y="{y - 6}" text-anchor="middle" '
            f'font-size="7" fill="#d09050">{round(temp)}°</text>'
        )

    for x, y, temp in low_points:
        elements.append(f'<circle cx="{x}" cy="{y}" r="2.5" fill="#5a7aa0"/>')
        elements.append(
            f'<text x="{x}" y="{y + 12}" text-anchor="middle" '
            f'font-size="7" fill="#5a7aa0">{round(temp)}°</text>'
        )

    return "".join(elements)


def _render_zone3_aqi(forecast: list, aqi_forecast: dict) -> str:
    """AQI strip: one colored rect per day."""
    rects = []
    max_aqi = max(
        (d.get("aqi", 0) for d in aqi_forecast.values() if d.get("aqi") is not None),
        default=0,
    )
    strip_height = 10 if max_aqi > 50 else 6

    for i, day in enumerate(forecast):
        x = DAY_START_X + i * DAY_SPACING
        w = DAY_SPACING * 0.8
        date_str = day.get("date", "")
        aqi_data = aqi_forecast.get(date_str, {})
        aqi = aqi_data.get("aqi")

        if aqi is not None:
            label = aqi_data.get("aqi_label", "Moderate")
            color = _AQI_COLORS.get(label, "#888")
            opacity = _AQI_OPACITIES.get(label, 0.3)
            rects.append(
                f'<rect x="{x}" y="{ZONE3_Y}" width="{w}" height="{strip_height}" '
                f'fill="{color}" opacity="{opacity}" rx="1"/>'
                f'<text x="{x + w / 2}" y="{ZONE3_Y + strip_height - 1}" '
                f'text-anchor="middle" font-size="6" fill="{color}">{aqi}</text>'
            )
        else:
            rects.append(
                f'<rect x="{x}" y="{ZONE3_Y}" width="{w}" height="2" '
                f'fill="#666" opacity="0.2" rx="1"/>'
                f'<text x="{x + w / 2}" y="{ZONE3_Y + 8}" '
                f'text-anchor="middle" font-size="6" fill="#888">--</text>'
            )

    # Left label
    rects.insert(
        0,
        f'<text x="35" y="{ZONE3_Y + strip_height / 2 + 3}" '
        f'font-size="7" fill="#888">AQI</text>',
    )

    return "".join(rects)


def _render_zone4_precip(forecast: list) -> str:
    """Precipitation bars with type-specific gradients and markers."""
    bars = []
    for i, day in enumerate(forecast):
        x = DAY_START_X + i * DAY_SPACING
        w = DAY_SPACING * 0.8
        precip_pct = day.get("precip_chance", 0) or 0
        precip_type = day.get("precip_type", "none")
        precip_timing = day.get("precip_timing", "")

        if precip_pct <= 0 or precip_type == "none":
            continue

        height = _precip_to_height(precip_pct)
        y = ZONE4_BASELINE - height

        # Gradient fill
        if precip_type in _PRECIP_GRADIENTS:
            grad_id = f"grad-{precip_type}"
            bars.append(
                f'<rect x="{x}" y="{y}" width="{w}" height="{height}" '
                f'fill="url(#{grad_id})" rx="1"/>'
            )
        else:
            bars.append(
                f'<rect x="{x}" y="{y}" width="{w}" height="{height}" '
                f'fill="#5b9bd5" opacity="0.6" rx="1"/>'
            )

        # Probability label above bar
        bars.append(
            f'<text x="{x + w / 2}" y="{y - 2}" text-anchor="middle" '
            f'font-size="6" fill="#888">{precip_pct}%</text>'
        )

        # Type marker below bar
        marker = _precip_marker(precip_type)
        if marker:
            bars.append(
                f'<text x="{x + w / 2}" y="{ZONE4_BASELINE + 10}" text-anchor="middle" '
                f'font-size="7" fill="#aaa">{marker}</text>'
            )

        # Timing label
        if precip_timing:
            bars.append(
                f'<text x="{x + w / 2}" y="{ZONE4_BASELINE + 18}" text-anchor="middle" '
                f'font-size="6" fill="#777">{precip_timing}</text>'
            )

    return "".join(bars)


def _render_zone5_labels(forecast: list) -> str:
    """Day abbreviation and condition summary."""
    labels = []
    for i, day in enumerate(forecast):
        x = DAY_START_X + i * DAY_SPACING + DAY_SPACING / 2
        day_name = day.get("day_name", "???")
        condition = day.get("condition", day.get("short_forecast", ""))

        # Shorten condition for display
        short_cond = _shorten_condition(condition)

        labels.append(
            f'<text x="{x}" y="{ZONE5_Y}" text-anchor="middle" '
            f'font-size="8" fill="#aaa" font-weight="600">{day_name.upper()}</text>'
            f'<text x="{x}" y="{ZONE5_Y + 12}" text-anchor="middle" '
            f'font-size="7" fill="#777">{short_cond}</text>'
        )

    return "".join(labels)


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


def _temp_to_y(temp: float, temp_min: float, temp_max: float) -> float:
    """Map temperature to SVG Y coordinate. Higher temp = lower Y."""
    if temp_max == temp_min:
        return (ZONE2_TOP + ZONE2_BOTTOM) / 2
    return ZONE2_TOP + (temp_max - temp) * (ZONE2_BOTTOM - ZONE2_TOP) / (
        temp_max - temp_min
    )


def _precip_to_height(
    probability_pct: float, max_height: float = ZONE4_MAX_HEIGHT
) -> float:
    """Map precipitation probability to bar height."""
    return probability_pct / 100.0 * max_height


def _nice_step(data_min: float, data_max: float, target_lines: int = 5) -> float:
    """Calculate a nice round step for gridlines."""
    import math

    range_val = data_max - data_min
    if range_val <= 0:
        return 10
    rough_step = range_val / target_lines
    magnitude = 10 ** math.floor(math.log10(rough_step))
    candidates = [1, 2, 5, 10, 20, 50]
    for c in candidates:
        step = c * magnitude
        if step >= rough_step:
            return step
    return candidates[-1] * magnitude


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
