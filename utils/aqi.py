"""Shared US AQI classification helpers."""

from __future__ import annotations


def aqi_label(aqi: int | None) -> str:
    """Convert a US AQI value to the EPA category label."""
    if aqi is None:
        return "unavailable"
    if aqi <= 50:
        return "Good"
    if aqi <= 100:
        return "Moderate"
    if aqi <= 150:
        return "Unhealthy for Sensitive Groups"
    if aqi <= 200:
        return "Unhealthy"
    if aqi <= 300:
        return "Very Unhealthy"
    return "Hazardous"


def aqi_color(aqi: int | None) -> str:
    """Return a readable text color for AQI inline display.

    The EPA signal colors are too bright for light email backgrounds, so these
    are darker variants used throughout the weather display.
    """
    if aqi is None:
        return "#666666"
    if aqi <= 50:
        return "#15803d"
    if aqi <= 100:
        return "#854d0e"
    if aqi <= 150:
        return "#c2410c"
    if aqi <= 200:
        return "#dc2626"
    if aqi <= 300:
        return "#7c3aed"
    return "#991b1b"
