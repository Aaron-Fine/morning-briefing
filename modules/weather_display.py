"""Weather display module — HTML table chart for email embedding.

Public API:
    render_weather_html(weather: dict, config: dict) -> str

Returns a complete HTML block (header + legend + chart) for embedding in the
Morning Digest email. Uses only <table>/<div>/<span> with inline styles so
the output survives Gmail's HTML sanitiser.

The chart renders:
  - a header row: location · current conditions · AQI · wind · humidity
  - a legend keying the AQI color bands used on the daily bars
  - a 7-day grid. Each row shows day name, low temp, a hi→lo gradient range
    bar with that day's AQI number overlaid at its scale position (0–200),
    normal and record hi/lo marker lines when enabled,
    the high temp, and a right column with condition + precip chance.
  - a thin blue precip underline when the day has measurable precip.

AQI numbers are positioned inside the bar cell using a single div with a
multi-stop linear-gradient background (temp range colored, rest gray) and
an inline-block spacer sized to the AQI's fraction of AQI_SCALE_MAX. This
replaces an earlier position:absolute approach that Gmail stripped.

Normal and record markers are positioned with the same spacer-table approach,
not absolute positioning, so they survive Gmail sanitization.
"""

import logging

from utils.aqi import aqi_color
from utils.time import format_display_date

log = logging.getLogger(__name__)

# --- Chart layout ---
DAY_COUNT = 7
# AQI values are positioned along the bar as a fraction of this ceiling.
# 200 is the top of the "Unhealthy" EPA band; higher values clamp to 100%.
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
        - render exception → text-only header
    """
    if not weather or not weather.get("forecast"):
        return ""

    weather_cfg = config.get("weather", {})
    show_aqi = weather_cfg.get("aqi_strip", True)
    show_normal = weather_cfg.get("normal_band", True)
    show_record = weather_cfg.get("record_band", True)

    try:
        header = _build_header_html(weather)
        legend = _build_legend_html(show_aqi, show_normal, show_record)
        chart = _build_chart_html(
            weather,
            show_aqi=show_aqi,
            show_normal=show_normal,
            show_record=show_record,
        )
        return f"{header}{legend}{chart}"
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
    date_str = format_display_date()

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
        f'<table class="wx-header" cellspacing="0" cellpadding="0" border="0" '
        f'style="width:100%;border-collapse:collapse;">'
        f'<tr><td>{header_text}</td><td class="wx-date">{date_str}</td></tr>'
        f'</table>'
        f"{aqi_alert}"
    )


def _build_legend_html(
    show_aqi: bool,
    show_normal: bool = False,
    show_record: bool = False,
) -> str:
    """Small band key shown above the 7-day chart.

    Keyed to the colors used by the per-day AQI overlays so readers can
    translate a number on a bar into a health category at a glance.
    """
    if not (show_aqi or show_normal or show_record):
        return ""
    bands = []
    if show_aqi:
        bands.extend([
            ("0-50 Good", "#15803d"),
            ("51-100 Moderate", "#854d0e"),
            ("101-150 USG", "#c2410c"),
            ("151-200 Unhealthy", "#dc2626"),
        ])
    if show_normal:
        bands.append(("Normal marker", "#508c50"))
    if show_record:
        bands.append(("Record marker", "#c0392b"))
    items = "".join(
        f'<td class="wx-legend-item">'
        f'<span class="wx-legend-swatch" style="background:{color};"></span>'
        f'<span class="wx-legend-label">{label}</span>'
        f'</td>'
        for label, color in bands
    )
    return (
        f'<table class="wx-legend" cellspacing="0" cellpadding="0" border="0">'
        f'<tr><td class="wx-legend-title">BANDS</td>{items}</tr></table>'
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


def _build_chart_html(
    weather: dict,
    show_aqi: bool = True,
    show_normal: bool = True,
    show_record: bool = True,
) -> str:
    """Build the HTML table chart — horizontal day rows with temp range bars."""
    forecast = weather.get("forecast", [])[:DAY_COUNT]
    aqi_forecast = weather.get("aqi_forecast", {}) or {}
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
        marker_overlay_html = ""
        if show_record:
            marker_overlay_html += _temp_marker_overlay_html(
                day,
                temp_min,
                temp_max,
                low_key="record_lo",
                high_key="record_hi",
                color="#c0392b",
                class_name="wx-record-band",
            )
        if show_normal:
            marker_overlay_html += _temp_marker_overlay_html(
                day,
                temp_min,
                temp_max,
                low_key="normal_lo",
                high_key="normal_hi",
                color="#508c50",
                class_name="wx-normal-band",
            )

        # AQI number overlay row (Gmail-safe: positioned via spacer td width
        # instead of position:absolute, which Gmail strips).
        aqi_overlay_html = ""
        if show_aqi:
            day_date = day.get("date")
            aqi_entry = aqi_forecast.get(day_date, {}) if day_date else {}
            aqi_val = aqi_entry.get("aqi")
            if aqi_val is not None:
                aqi_pct = max(0.0, min(100.0, aqi_val / AQI_SCALE_MAX * 100.0))
                aqi_col = _aqi_text_color(aqi_val)
                # When AQI sits near the right edge, right-align the label so
                # it doesn't overflow the bar.
                if aqi_pct >= 85:
                    aqi_overlay_html = (
                        f'<tr><td colspan="3" style="padding:1px 0 0;">'
                        f'<div style="font-size:8px;color:{aqi_col};'
                        f'font-weight:700;text-align:right;line-height:1;">'
                        f'{aqi_val}</div></td></tr>'
                    )
                else:
                    # Spacer cell + AQI cell. Narrow AQI cell keeps the number
                    # centered on the mark; trailing cell absorbs remainder.
                    spacer_pct = max(0.0, aqi_pct - 2)
                    aqi_overlay_html = (
                        f'<tr><td colspan="3" style="padding:1px 0 0;">'
                        f'<table cellspacing="0" cellpadding="0" border="0" '
                        f'style="width:100%;border-collapse:collapse;">'
                        f'<tr>'
                        f'<td style="width:{spacer_pct:.1f}%;font-size:0;'
                        f'line-height:0;padding:0;"></td>'
                        f'<td style="font-size:8px;color:{aqi_col};'
                        f'font-weight:700;line-height:1;padding:0;'
                        f'white-space:nowrap;">{aqi_val}</td>'
                        f'<td style="padding:0;"></td>'
                        f'</tr></table></td></tr>'
                    )

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
            f'<td class="wx-day-cell">{day_name.upper()}</td>'
            f'<td class="wx-temp-cell wx-lo-temp">{lo_str}</td>'
            f'<td class="wx-gradient-cell">'
            f'<table cellspacing="0" cellpadding="0" border="0" '
            f'class="wx-temp-bar">'
            f'<tr class="wx-bar-row">'
            f'<td class="wx-bar-pad" style="width:{lo_pct:.1f}%;"></td>'
            f'<td class="wx-bar-fill" style="width:{bar_width:.1f}%;"></td>'
            f'<td class="wx-bar-pad"></td>'
            f'</tr>'
            f'{marker_overlay_html}'
            f'{aqi_overlay_html}'
            f'</table>'
            f'</td>'
            f'<td class="wx-temp-cell wx-hi-temp">{hi_str}</td>'
            f'<td class="wx-condition-cell">{right_col}</td>'
            f'</tr>'
        )

        # Precip underline + separator row
        rows.append(
            f'<tr style="{border}">'
            f'<td></td><td></td>'
            f'<td class="wx-precip-cell">{precip_bar_html}</td>'
            f'<td colspan="2"></td>'
            f'</tr>'
        )

    return (
        '<table cellspacing="0" cellpadding="0" border="0" '
        'class="wx-chart">'
        + "".join(rows)
        + "</table>"
    )


# ====================================================================
# Helpers
# ====================================================================


def _temp_marker_overlay_html(
    day: dict,
    temp_min: float,
    temp_max: float,
    *,
    low_key: str,
    high_key: str,
    color: str,
    class_name: str,
) -> str:
    """Build Gmail-safe vertical marker lines for low/high reference temps."""
    markers = [
        _temp_to_pct(value, temp_min, temp_max)
        for value in (day.get(low_key), day.get(high_key))
        if value is not None
    ]
    if not markers:
        return ""

    markers = sorted(markers)
    marker_width = 0.6
    cells = []
    cursor = 0.0
    for pct in markers:
        pad_width = max(pct - cursor - marker_width / 2.0, 0.0)
        if pad_width:
            cells.append(
                f'<td style="width:{pad_width:.2f}%;font-size:0;line-height:0;'
                f'padding:0;"></td>'
            )
        cells.append(
            f'<td class="{class_name}" style="width:{marker_width:.2f}%;height:14px;'
            f'background:{color};opacity:0.8;font-size:0;line-height:0;'
            f'padding:0;"></td>'
        )
        cursor = min(pct + marker_width / 2.0, 100.0)
    if cursor < 100.0:
        cells.append(
            '<td style="font-size:0;line-height:0;padding:0;"></td>'
        )
    return (
        f'<tr><td colspan="3" style="padding:1px 0 0;">'
        f'<table cellspacing="0" cellpadding="0" border="0" '
        f'style="width:100%;border-collapse:collapse;">'
        f'<tr>'
        f'{"".join(cells)}'
        f'</tr></table></td></tr>'
    )


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
    return aqi_color(aqi)


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
