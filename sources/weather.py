"""Fetch weather from Open-Meteo (free, no API key required)."""

import logging
import requests

log = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_weather(config: dict) -> dict:
    """Return current conditions and 3-day forecast for configured location.
    
    Returns dict: {current_temp_f, condition, high_f, low_f, forecast: [...]}
    """
    loc = config.get("location", {})
    lat = loc.get("latitude", 41.737)
    lon = loc.get("longitude", -111.834)

    try:
        resp = requests.get(
            OPEN_METEO_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "forecast_days": 5,
                "timezone": loc.get("timezone", "America/Denver"),
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        current = data.get("current", {})
        daily = data.get("daily", {})

        forecast_days = []
        for i in range(min(5, len(daily.get("time", [])))):
            forecast_days.append({
                "date": daily["time"][i],
                "high_f": round(daily["temperature_2m_max"][i]),
                "low_f": round(daily["temperature_2m_min"][i]),
                "precip_chance": daily["precipitation_probability_max"][i],
                "condition": _weather_code_to_text(daily["weather_code"][i]),
            })

        return {
            "current_temp_f": round(current.get("temperature_2m", 0)),
            "condition": _weather_code_to_text(current.get("weather_code", 0)),
            "wind_mph": round(current.get("wind_speed_10m", 0)),
            "today_high_f": forecast_days[0]["high_f"] if forecast_days else None,
            "today_low_f": forecast_days[0]["low_f"] if forecast_days else None,
            "forecast": forecast_days,
            "city": loc.get("city", "Logan"),
            "state": loc.get("state", "UT"),
        }

    except Exception as e:
        log.error(f"Weather fetch failed: {e}")
        return {
            "current_temp_f": None,
            "condition": "unavailable",
            "forecast": [],
            "city": loc.get("city", "Logan"),
            "state": loc.get("state", "UT"),
        }


def _weather_code_to_text(code: int) -> str:
    """Convert WMO weather code to human-readable description."""
    codes = {
        0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Rime fog",
        51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
        61: "Light rain", 63: "Rain", 65: "Heavy rain",
        71: "Light snow", 73: "Snow", 75: "Heavy snow",
        77: "Snow grains", 80: "Light showers", 81: "Showers", 82: "Heavy showers",
        85: "Light snow showers", 86: "Snow showers",
        95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Severe thunderstorm",
    }
    return codes.get(code, "Unknown")
