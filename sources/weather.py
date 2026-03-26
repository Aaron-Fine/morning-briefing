"""Fetch weather from Open-Meteo (free, no API key required)."""

import logging
from datetime import datetime
import requests

log = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_AQI_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"


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
                "forecast_days": 7,
                "timezone": loc.get("timezone", "America/Denver"),
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        current = data.get("current", {})
        daily = data.get("daily", {})

        forecast_days = []
        for i in range(min(7, len(daily.get("time", [])))):
            day_date = datetime.strptime(daily["time"][i], "%Y-%m-%d")
            forecast_days.append({
                "date": daily["time"][i],
                "day_name": day_date.strftime("%a"),
                "high_f": round(daily["temperature_2m_max"][i]),
                "low_f": round(daily["temperature_2m_min"][i]),
                "precip_chance": daily["precipitation_probability_max"][i],
                "condition": _weather_code_to_text(daily["weather_code"][i]),
            })

        result = {
            "current_temp_f": round(current.get("temperature_2m", 0)),
            "condition": _weather_code_to_text(current.get("weather_code", 0)),
            "wind_mph": round(current.get("wind_speed_10m", 0)),
            "today_high_f": forecast_days[0]["high_f"] if forecast_days else None,
            "today_low_f": forecast_days[0]["low_f"] if forecast_days else None,
            "forecast": forecast_days,
            "city": loc.get("city", "Logan"),
            "state": loc.get("state", "UT"),
        }

        # Fetch air quality data
        aqi = _fetch_air_quality(lat, lon)
        result.update(aqi)

        return result

    except Exception as e:
        log.error(f"Weather fetch failed: {e}")
        return {
            "current_temp_f": None,
            "condition": "unavailable",
            "forecast": [],
            "city": loc.get("city", "Logan"),
            "state": loc.get("state", "UT"),
            "aqi": None,
            "aqi_label": "unavailable",
            "pm2_5": None,
            "pm10": None,
        }


def _fetch_air_quality(lat: float, lon: float) -> dict:
    """Fetch current air quality from Open-Meteo (free, no key needed).

    Returns dict: {aqi, aqi_label, pm2_5, pm10}
    Important for Cache Valley which has severe winter inversions.
    """
    try:
        resp = requests.get(
            OPEN_METEO_AQI_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "us_aqi,pm2_5,pm10",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        current = data.get("current", {})

        aqi = current.get("us_aqi")
        return {
            "aqi": aqi,
            "aqi_label": _aqi_to_label(aqi) if aqi is not None else "unavailable",
            "pm2_5": current.get("pm2_5"),
            "pm10": current.get("pm10"),
        }
    except Exception as e:
        log.warning(f"Air quality fetch failed: {e}")
        return {"aqi": None, "aqi_label": "unavailable", "pm2_5": None, "pm10": None}


def _aqi_to_label(aqi: int) -> str:
    """Convert US AQI value to category label."""
    if aqi <= 50:
        return "Good"
    elif aqi <= 100:
        return "Moderate"
    elif aqi <= 150:
        return "Unhealthy for Sensitive Groups"
    elif aqi <= 200:
        return "Unhealthy"
    elif aqi <= 300:
        return "Very Unhealthy"
    else:
        return "Hazardous"


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
