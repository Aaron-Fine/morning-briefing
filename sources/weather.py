"""Fetch weather from NWS (primary) with Open-Meteo fallback, AirNow AQI, and JSON caching."""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

log = logging.getLogger(__name__)

# --- Endpoints ---
NWS_POINTS_URL = "https://api.weather.gov/points/{lat},{lon}"
NWS_STATION_OBS_URL = "https://api.weather.gov/stations/{station}/observations/latest"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_AQI_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OPEN_METEO_CLIMATE_URL = "https://climate-api.open-meteo.com/v1/climate"
AIRNOW_CURRENT_URL = "https://www.airnowapi.org/aq/observation/latLong/current/"
AIRNOW_FORECAST_URL = "https://www.airnowapi.org/aq/forecast/latLong/"
UTAH_DEQ_FORECAST_URL = "https://air.utah.gov/forecast.php"

# --- Cache directory ---
CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "weather"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# --- NOAA 1991-2020 normals for Logan, UT (approx KLGU) ---
# Month index 1-12.  Values are daily normal high/low.
_LOGAN_NORMALS = {
    1: (28.8, 14.0),
    2: (31.5, 17.8),
    3: (40.3, 25.5),
    4: (48.6, 30.9),
    5: (59.4, 38.5),
    6: (70.7, 46.3),
    7: (83.3, 55.4),
    8: (81.1, 53.6),
    9: (71.4, 43.8),
    10: (54.5, 32.8),
    11: (41.0, 22.7),
    12: (28.8, 15.3),
}

# Approximate monthly record highs/lows for Logan
_LOGAN_RECORDS = {
    1: (60, -25),
    2: (63, -23),
    3: (75, -5),
    4: (82, 10),
    5: (93, 18),
    6: (100, 28),
    7: (103, 35),
    8: (101, 32),
    9: (97, 16),
    10: (85, 2),
    11: (73, -14),
    12: (62, -20),
}

# WMO weather code mapping (Open-Meteo fallback)
_WMO_CODES = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Light freezing drizzle",
    57: "Freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light showers",
    81: "Showers",
    82: "Heavy showers",
    85: "Light snow showers",
    86: "Snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm w/ hail",
    99: "Severe thunderstorm",
}


# ====================================================================
# Public API
# ====================================================================


def fetch_weather(config: dict) -> dict:
    """Return current conditions and 7-day forecast.

    Tries NWS first, falls back to Open-Meteo silently.
    Enriches each forecast day with precip_type, precip_timing,
    short_forecast, detailed_forecast, normals, and records.
    Fetches AQI from AirNow (if key present) with Open-Meteo fallback.

    Returns dict compatible with the existing pipeline contract:
        current_temp_f, condition, wind_mph, wind_direction, humidity,
        today_high_f, today_low_f, forecast: [day_dicts],
        city, state, aqi, aqi_label, pm2_5, pm10,
        aqi_forecast: {date_str: {aqi, aqi_label}},
        normals: [{date, normal_hi, normal_lo, record_hi, record_lo}],
    """
    loc = config.get("location", {})
    lat = loc.get("latitude", 41.737)
    lon = loc.get("longitude", -111.834)
    nws_station = config.get("weather", {}).get("nws_station", "KLGU")
    airnow_key = os.environ.get("AIRNOW_API_KEY")

    # --- Primary: NWS ---
    nws_data = _fetch_nws(lat, lon, nws_station)
    if nws_data and nws_data.get("forecast"):
        log.info("weather: NWS data fetched successfully")
        forecast = nws_data["forecast"]
        current = nws_data.get("current", {})
    else:
        log.warning("weather: NWS fetch failed, falling back to Open-Meteo")
        om_data = _fetch_open_meteo(lat, lon, loc.get("timezone", "America/Denver"))
        forecast = om_data.get("forecast", [])
        current = om_data.get("current", {})

    # --- AQI ---
    aqi_data = _fetch_airnow_forecast(lat, lon, airnow_key) if airnow_key else {}
    if not aqi_data:
        aqi_data = _fetch_open_meteo_aqi(lat, lon)

    # --- Normals & records ---
    normals_records = _compute_normals_and_records(forecast)

    # --- Enrich forecast days ---
    for i, day in enumerate(forecast):
        day["precip_type"] = _classify_precip(
            day.get("short_forecast", ""),
            day.get("detailed_forecast", ""),
            day.get("high_f"),
            day.get("low_f"),
        )
        day["precip_timing"] = _extract_precip_timing(day.get("detailed_forecast", ""))
        if i < len(normals_records):
            nr = normals_records[i]
            day["normal_hi"] = nr["normal_hi"]
            day["normal_lo"] = nr["normal_lo"]
            day["record_hi"] = nr["record_hi"]
            day["record_lo"] = nr["record_lo"]

    # --- Current AQI ---
    current_aqi = aqi_data.get("current_aqi")
    current_aqi_label = aqi_data.get("current_aqi_label", "unavailable")

    result = {
        "current_temp_f": current.get("temperature_f"),
        "condition": current.get("condition", "unavailable"),
        "wind_mph": current.get("wind_mph"),
        "wind_direction": current.get("wind_direction"),
        "humidity": current.get("humidity"),
        "today_high_f": forecast[0]["high_f"] if forecast else None,
        "today_low_f": forecast[0]["low_f"] if forecast else None,
        "forecast": forecast,
        "city": loc.get("city", "Logan"),
        "state": loc.get("state", "UT"),
        "aqi": current_aqi,
        "aqi_label": current_aqi_label,
        "pm2_5": aqi_data.get("pm2_5"),
        "pm10": aqi_data.get("pm10"),
        "aqi_forecast": aqi_data.get("forecast", {}),
        "normals": normals_records,
    }

    return result


# ====================================================================
# NWS fetching
# ====================================================================

_NWS_HEADERS = {
    "User-Agent": "MorningDigest/1.0 (morningDigest@lurkers.us)",
    "Accept": "application/geo+json",
}


def _fetch_nws(lat: float, lon: float, nws_station: str) -> dict | None:
    """Fetch forecast and current obs from NWS.  Returns None on failure."""
    try:
        # Step 1: get forecast URL from points endpoint
        points = _cache_read("nws_points", ttl_hours=24)
        if not points:
            resp = requests.get(
                NWS_POINTS_URL.format(lat=lat, lon=lon),
                headers=_NWS_HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
            points = resp.json()
            _cache_write("nws_points", points)

        forecast_url = points.get("properties", {}).get("forecast")
        if not forecast_url:
            log.warning("weather: no forecast URL in NWS points response")
            return None

        # Step 2: fetch forecast
        forecast_raw = _cache_read("nws_forecast", ttl_hours=2)
        if not forecast_raw:
            resp = requests.get(forecast_url, headers=_NWS_HEADERS, timeout=10)
            resp.raise_for_status()
            forecast_raw = resp.json()
            _cache_write("nws_forecast", forecast_raw)

        # Step 3: fetch current observations from station
        current_raw = _cache_read(f"nws_obs_{nws_station}", ttl_hours=2)
        if not current_raw:
            resp = requests.get(
                NWS_STATION_OBS_URL.format(station=nws_station),
                headers=_NWS_HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
            current_raw = resp.json()
            _cache_write(f"nws_obs_{nws_station}", current_raw)

        # Parse into our format
        forecast = _parse_nws_forecast(forecast_raw)
        current = _parse_nws_current(current_raw)

        return {"forecast": forecast, "current": current}

    except Exception as e:
        log.error(f"weather: NWS fetch failed: {e}")
        return None


def _parse_nws_forecast(raw: dict) -> list[dict]:
    """Parse NWS forecast GeoJSON into list of day dicts."""
    periods = raw.get("properties", {}).get("periods", [])
    # NWS returns 14 periods (day/night for 7 days).  We want one dict per calendar day.
    days: dict[str, dict] = {}
    for p in periods:
        date_str = p.get("startTime", "")[:10]  # YYYY-MM-DD
        if not date_str:
            continue
        if date_str not in days:
            day_date = datetime.strptime(date_str, "%Y-%m-%d")
            days[date_str] = {
                "date": date_str,
                "day_name": day_date.strftime("%a"),
                "is_daytime": p.get("isDaytime", True),
                "short_forecast": p.get("shortForecast", ""),
                "detailed_forecast": p.get("detailedForecast", ""),
                "wind_speed": p.get("windSpeed", ""),
                "wind_direction": p.get("windDirection", ""),
                "precip_chance": p.get("probabilityOfPrecipitation", {}).get("value"),
            }
        # Merge daytime/nighttime data
        existing = days[date_str]
        temp_f = p.get("temperature")
        if temp_f is not None:
            if existing.get("is_daytime"):
                existing["high_f"] = round(temp_f)
            else:
                existing["low_f"] = round(temp_f)
        # Combine text forecasts
        if p.get("isDaytime"):
            existing["short_forecast"] = p.get(
                "shortForecast", existing.get("short_forecast", "")
            )
        else:
            # Append night info to detailed forecast
            existing["detailed_forecast"] = (
                existing.get("detailed_forecast", "")
                + " "
                + p.get("detailedForecast", "")
            ).strip()

    # Ensure we have at most 7 days
    result = []
    for i, (date_str, day) in enumerate(sorted(days.items())):
        if i >= 7:
            break
        day.setdefault("high_f", day.get("low_f"))
        day.setdefault("low_f", day.get("high_f"))
        day.setdefault("precip_chance", 0)
        day.setdefault("condition", day.get("short_forecast", "Unknown"))
        result.append(day)

    return result


def _parse_nws_current(raw: dict) -> dict:
    """Parse NWS station observation into current conditions dict."""
    props = raw.get("properties", {})
    temp_c = props.get("temperature", {}).get("value")
    temp_f = round(temp_c * 9 / 5 + 32) if temp_c is not None else None

    wind_mph = None
    wind_speed_ms = props.get("windSpeed", {}).get("value")
    if wind_speed_ms is not None:
        wind_mph = round(wind_speed_ms * 2.237)

    return {
        "temperature_f": temp_f,
        "condition": props.get("textDescription", "Unknown"),
        "wind_mph": wind_mph,
        "wind_direction": props.get("windDirection", {}).get("value"),
        "humidity": props.get("relativeHumidity", {}).get("value"),
    }


# ====================================================================
# Open-Meteo fallback
# ====================================================================


def _fetch_open_meteo(lat: float, lon: float, tz: str) -> dict:
    """Fetch forecast from Open-Meteo as fallback."""
    try:
        cached = _cache_read("open_meteo", ttl_hours=2)
        if cached:
            return _parse_open_meteo(cached, tz)

        resp = requests.get(
            OPEN_METEO_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code,wind_speed_10m_max,wind_direction_10m_dominant",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "forecast_days": 7,
                "timezone": tz,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        _cache_write("open_meteo", data)
        return _parse_open_meteo(data, tz)

    except Exception as e:
        log.error(f"weather: Open-Meteo fetch failed: {e}")
        return {"forecast": [], "current": {}}


def _parse_open_meteo(raw: dict, tz: str) -> dict:
    """Parse Open-Meteo JSON into our forecast/current format."""
    current = raw.get("current", {})
    daily = raw.get("daily", {})

    forecast = []
    for i in range(min(7, len(daily.get("time", [])))):
        day_date = datetime.strptime(daily["time"][i], "%Y-%m-%d")
        wmo = daily.get("weather_code", [0] * 7)[i]
        forecast.append(
            {
                "date": daily["time"][i],
                "day_name": day_date.strftime("%a"),
                "high_f": round(daily["temperature_2m_max"][i]),
                "low_f": round(daily["temperature_2m_min"][i]),
                "precip_chance": daily.get("precipitation_probability_max", [0] * 7)[i],
                "condition": _wmo_to_text(wmo),
                "short_forecast": _wmo_to_text(wmo),
                "detailed_forecast": _wmo_to_text(wmo),
                "wind_speed": daily.get("wind_speed_10m_max", [0] * 7)[i],
                "wind_direction": daily.get("wind_direction_10m_dominant", [""] * 7)[i],
            }
        )

    return {
        "forecast": forecast,
        "current": {
            "temperature_f": round(current.get("temperature_2m", 0)),
            "condition": _wmo_to_text(current.get("weather_code", 0)),
            "wind_mph": round(current.get("wind_speed_10m", 0)),
            "humidity": current.get("relative_humidity_2m"),
        },
    }


def _wmo_to_text(code: int) -> str:
    return _WMO_CODES.get(code, "Unknown")


# ====================================================================
# AQI fetching
# ====================================================================


def _fetch_airnow_forecast(lat: float, lon: float, api_key: str | None) -> dict:
    """Fetch current and forecast AQI from AirNow API.

    Returns dict with current_aqi, current_aqi_label, pm2_5, pm10,
    and forecast: {date_str: {aqi, aqi_label}}.
    """
    if not api_key:
        return {}

    result: dict = {"forecast": {}}

    # Current AQI
    try:
        cached = _cache_read("airnow_current", ttl_hours=1)
        if cached:
            result.update(cached)
        else:
            resp = requests.get(
                AIRNOW_CURRENT_URL,
                params={
                    "format": "application/json",
                    "latitude": lat,
                    "longitude": lon,
                    "distance": 25,
                    "API_KEY": api_key,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                obs = data[0]
                aqi = obs.get("AQI")
                result["current_aqi"] = aqi
                result["current_aqi_label"] = (
                    _aqi_to_label(aqi) if aqi is not None else "unavailable"
                )
                result["pm2_5"] = obs.get("PM2.5")
                result["pm10"] = obs.get("PM10")
            _cache_write("airnow_current", result)
    except Exception as e:
        log.warning(f"weather: AirNow current AQI fetch failed: {e}")

    # Forecast AQI
    try:
        cached = _cache_read("airnow_forecast", ttl_hours=1)
        if cached:
            result["forecast"] = cached
        else:
            resp = requests.get(
                AIRNOW_FORECAST_URL,
                params={
                    "format": "application/json",
                    "latitude": lat,
                    "longitude": lon,
                    "API_KEY": api_key,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            forecast_dict = {}
            for item in data:
                date_str = item.get("DateForecast", "")[:10]
                if date_str:
                    aqi = item.get("AQI")
                    forecast_dict[date_str] = {
                        "aqi": aqi,
                        "aqi_label": _aqi_to_label(aqi)
                        if aqi is not None
                        else "Moderate",
                    }
            result["forecast"] = forecast_dict
            _cache_write("airnow_forecast", forecast_dict)
    except Exception as e:
        log.warning(f"weather: AirNow forecast AQI fetch failed: {e}")

    return result


def _fetch_open_meteo_aqi(lat: float, lon: float) -> dict:
    """Fallback AQI from Open-Meteo air quality API."""
    try:
        cached = _cache_read("open_meteo_aqi", ttl_hours=1)
        if cached:
            return cached

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

        result = {
            "current_aqi": aqi,
            "current_aqi_label": _aqi_to_label(aqi)
            if aqi is not None
            else "unavailable",
            "pm2_5": current.get("pm2_5"),
            "pm10": current.get("pm10"),
            "forecast": {},
        }
        _cache_write("open_meteo_aqi", result)
        return result
    except Exception as e:
        log.warning(f"weather: Open-Meteo AQI fetch failed: {e}")
        return {"current_aqi": None, "current_aqi_label": "unavailable", "forecast": {}}


# ====================================================================
# Normals and records
# ====================================================================


def _compute_normals_and_records(forecast: list[dict]) -> list[dict]:
    """Compute daily normals and records for the forecast window.

    Uses hardcoded NOAA 1991-2020 tables for Logan, UT with linear
    monthly interpolation for daily resolution.
    """
    result = []
    for day in forecast:
        date_str = day.get("date", "")
        if not date_str:
            continue
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        normal_hi, normal_lo = _interpolate_monthly(_LOGAN_NORMALS, dt)
        record_hi, record_lo = _interpolate_monthly(_LOGAN_RECORDS, dt)

        result.append(
            {
                "date": date_str,
                "normal_hi": round(normal_hi, 1),
                "normal_lo": round(normal_lo, 1),
                "record_hi": record_hi,
                "record_lo": record_lo,
            }
        )

    return result


def _interpolate_monthly(table: dict, dt: datetime) -> tuple[float, float]:
    """Linearly interpolate between monthly values for a given date.

    Uses the 15th of each month as anchor points.
    """
    month = dt.month
    day = dt.day

    # Value for the 15th of this month
    hi_15, lo_15 = table[month]

    # Value for the 15th of next month
    next_month = month + 1 if month < 12 else 1
    hi_next, lo_next = table[next_month]

    # Day of year for the 15th of this month and next
    if month < 12:
        day_15_this = datetime(dt.year, month, 15).timetuple().tm_yday
        day_15_next = datetime(dt.year, next_month, 15).timetuple().tm_yday
    else:
        day_15_this = datetime(dt.year, 12, 15).timetuple().tm_yday
        day_15_next = datetime(dt.year + 1, 1, 15).timetuple().tm_yday

    day_of_year = dt.timetuple().tm_yday

    # Linear interpolation
    if day_15_next > day_15_this:
        frac = (day_of_year - day_15_this) / (day_15_next - day_15_this)
    else:
        # 跨越 year boundary
        days_in_range = (365 - day_15_this) + day_15_next
        frac = (
            ((365 - day_15_this) + day_of_year) / days_in_range
            if day_of_year < day_15_next
            else 0.0
        )

    frac = max(0.0, min(1.0, frac))
    hi = hi_15 + frac * (hi_next - hi_15)
    lo = lo_15 + frac * (lo_next - lo_15)

    return hi, lo


# ====================================================================
# Precipitation classification and timing
# ====================================================================


def _classify_precip(
    short_forecast: str,
    detailed_forecast: str,
    temp_hi: float | None,
    temp_lo: float | None,
) -> str:
    """Classify precipitation type from NWS forecast text.

    Priority: freezing_rain > mix > thunderstorm > snow > rain > none
    """
    text = f"{short_forecast} {detailed_forecast}".lower()

    has_thunder = any(w in text for w in ["thunderstorm", "thunder", "t-storm"])
    has_snow = any(w in text for w in ["snow", "flurries", "blizzard", "winter storm"])
    has_rain = any(w in text for w in ["rain", "shower", "drizzle", "precipitation"])
    has_freezing = any(
        w in text for w in ["freezing rain", "ice", "sleet", "freezing drizzle"]
    )
    has_mix = any(w in text for w in ["rain and snow", "snow and rain", "wintry mix"])

    if has_freezing:
        return "freezing_rain"
    if has_mix or (has_snow and has_rain):
        return "mix"
    if has_thunder:
        return "thunderstorm"
    if has_snow:
        return "snow"
    if has_rain:
        return "rain"
    return "none"


def _extract_precip_timing(detailed: str) -> str:
    """Extract precipitation timing from NWS detailed forecast."""
    text = detailed.lower()
    if "after noon" in text or "in the afternoon" in text:
        return "PM"
    if "before noon" in text or "in the morning" in text:
        return "AM"
    if "in the evening" in text or "after midnight" in text:
        return "eve"
    if "mainly" in text and "night" in text:
        return "night"
    return ""


# ====================================================================
# AQI label helper
# ====================================================================


def _aqi_to_label(aqi: int | None) -> str:
    """Convert US AQI value to EPA category label."""
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


# ====================================================================
# JSON cache helpers
# ====================================================================


def _cache_read(key: str, ttl_hours: float = 2) -> dict | None:
    """Read a cached JSON file if it exists and is not stale."""
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    if age_hours > ttl_hours:
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _cache_write(key: str, data: dict) -> None:
    """Write data to a JSON cache file."""
    path = CACHE_DIR / f"{key}.json"
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        log.warning(f"weather: failed to write cache {key}: {e}")
