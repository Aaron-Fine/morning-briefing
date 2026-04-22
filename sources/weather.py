"""Fetch weather from NWS (primary) with Open-Meteo fallback, AirNow AQI, and JSON caching."""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import yaml

from sources._http import http_get_json
from utils.aqi import aqi_label

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# --- Endpoints ---
NWS_POINTS_URL = "https://api.weather.gov/points/{lat},{lon}"
NWS_STATION_OBS_URL = "https://api.weather.gov/stations/{station}/observations/latest"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_AQI_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OPEN_METEO_HISTORICAL_URL = "https://archive-api.open-meteo.com/v1/archive"
AIRNOW_CURRENT_URL = "https://www.airnowapi.org/aq/observation/latLong/current/"
AIRNOW_FORECAST_URL = "https://www.airnowapi.org/aq/forecast/latLong/"
UTAH_DEQ_FORECAST_URL = "https://air.utah.gov/forecast.php"

# --- Cache directory ---
CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "weather"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def _load_yaml(filename: str):
    """Load a YAML data file from the data/ directory."""
    with open(DATA_DIR / filename) as f:
        return yaml.safe_load(f)


def _load_monthly_table(filename: str) -> dict[int, tuple[float, float]]:
    """Load a month-keyed YAML file into {int: (hi, lo)} format."""
    raw = _load_yaml(filename)
    return {int(k): tuple(v) for k, v in raw.items()}


# Loaded from data/ files; see data/*.yaml for sources and notes.
_FALLBACK_NORMALS = _load_monthly_table("weather_fallback_normals.yaml")
_FALLBACK_RECORDS = _load_monthly_table("weather_fallback_records.yaml")
_WMO_CODES = {int(k): v for k, v in _load_yaml("wmo_codes.yaml").items()}


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
    normals_records = _compute_normals_and_records(lat, lon, forecast)

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

_NWS_HEADERS = {"Accept": "application/geo+json"}


def _fetch_nws(lat: float, lon: float, nws_station: str) -> dict | None:
    """Fetch forecast and current obs from NWS.  Returns None on failure."""
    points = _cache_read("nws_points", ttl_hours=24)
    if not points:
        points = http_get_json(
            NWS_POINTS_URL.format(lat=lat, lon=lon),
            headers=_NWS_HEADERS,
            timeout=10,
            label="NWS points",
        )
        if points is None:
            return None
        _cache_write("nws_points", points)

    forecast_url = points.get("properties", {}).get("forecast")
    if not forecast_url:
        log.warning("weather: no forecast URL in NWS points response")
        return None

    forecast_raw = _cache_read("nws_forecast", ttl_hours=2)
    if not forecast_raw:
        forecast_raw = http_get_json(
            forecast_url, headers=_NWS_HEADERS, timeout=10, label="NWS forecast"
        )
        if forecast_raw is None:
            return None
        _cache_write("nws_forecast", forecast_raw)

    current_raw = _cache_read(f"nws_obs_{nws_station}", ttl_hours=2)
    if not current_raw:
        current_raw = http_get_json(
            NWS_STATION_OBS_URL.format(station=nws_station),
            headers=_NWS_HEADERS,
            timeout=10,
            label=f"NWS obs {nws_station}",
        )
        if current_raw is None:
            return None
        _cache_write(f"nws_obs_{nws_station}", current_raw)

    return {
        "forecast": _parse_nws_forecast(forecast_raw),
        "current": _parse_nws_current(current_raw),
    }


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
            if p.get("isDaytime"):
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
        # NWS sometimes returns a trailing night-only period with no daytime
        # high. Mirror the available temp so the day renders a sensible value,
        # or skip entirely if both are missing.
        if day.get("high_f") is None and day.get("low_f") is None:
            log.debug(f"Skipping forecast day {date_str} — no temperatures")
            continue
        if day.get("high_f") is None:
            day["high_f"] = day["low_f"]
        if day.get("low_f") is None:
            day["low_f"] = day["high_f"]
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
    cached = _cache_read("open_meteo", ttl_hours=2)
    if cached:
        return _parse_open_meteo(cached, tz)

    data = http_get_json(
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
        label="Open-Meteo",
    )
    if data is None:
        return {"forecast": [], "current": {}}
    _cache_write("open_meteo", data)
    return _parse_open_meteo(data, tz)


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
    cached = _cache_read("airnow_current", ttl_hours=1)
    if cached:
        result.update(cached)
    else:
        data = http_get_json(
            AIRNOW_CURRENT_URL,
            params={
                "format": "application/json",
                "latitude": lat,
                "longitude": lon,
                "distance": 25,
                "API_KEY": api_key,
            },
            timeout=10,
            label="AirNow current",
        )
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

    # Forecast AQI
    cached = _cache_read("airnow_forecast", ttl_hours=1)
    if cached:
        result["forecast"] = cached
    else:
        data = http_get_json(
            AIRNOW_FORECAST_URL,
            params={
                "format": "application/json",
                "latitude": lat,
                "longitude": lon,
                "API_KEY": api_key,
            },
            timeout=10,
            label="AirNow forecast",
        )
        if data is not None:
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

    return result


def _fetch_open_meteo_aqi(lat: float, lon: float) -> dict:
    """Fallback AQI from Open-Meteo air quality API."""
    cached = _cache_read("open_meteo_aqi", ttl_hours=1)
    if cached:
        return cached

    data = http_get_json(
        OPEN_METEO_AQI_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "us_aqi,pm2_5,pm10",
            "hourly": "us_aqi",
            "forecast_days": 7,
        },
        timeout=10,
        label="Open-Meteo AQI",
    )
    if data is None:
        return {"current_aqi": None, "current_aqi_label": "unavailable", "forecast": {}}

    current = data.get("current", {})
    aqi = current.get("us_aqi")

    forecast: dict = {}
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    aqi_values = hourly.get("us_aqi", [])
    for ts, val in zip(times, aqi_values):
        if val is None:
            continue
        date_str = ts[:10]
        if date_str not in forecast or val > forecast[date_str]["aqi"]:
            forecast[date_str] = {"aqi": val, "aqi_label": _aqi_to_label(val)}

    result = {
        "current_aqi": aqi,
        "current_aqi_label": _aqi_to_label(aqi) if aqi is not None else "unavailable",
        "pm2_5": current.get("pm2_5"),
        "pm10": current.get("pm10"),
        "forecast": forecast,
    }
    _cache_write("open_meteo_aqi", result)
    return result


# ====================================================================
# Normals and records
# ====================================================================


def _compute_normals_and_records(
    lat: float, lon: float, forecast: list[dict]
) -> list[dict]:
    """Compute daily normals and records for the forecast window.

    Fetches multi-year historical averages from Open-Meteo for the
    location.  Falls back to hardcoded Logan, UT tables on failure.
    Records always use the hardcoded fallback (no free API exists).
    """
    normals_table = _fetch_historical_normals(lat, lon)
    if normals_table is None:
        log.info("weather: using fallback normals for Logan, UT")
        normals_table = _FALLBACK_NORMALS

    result = []
    for day in forecast:
        date_str = day.get("date", "")
        if not date_str:
            continue
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        normal_hi, normal_lo = _interpolate_monthly(normals_table, dt)
        record_hi, record_lo = _interpolate_monthly(_FALLBACK_RECORDS, dt)

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


def _fetch_historical_normals(lat: float, lon: float) -> dict | None:
    """Fetch monthly normals from Open-Meteo Historical API.

    Queries the last 5 complete years of daily temperature data,
    averages highs and lows by month, and returns a dict keyed by
    month (1-12) with (avg_hi, avg_lo) tuples — same shape as
    _FALLBACK_NORMALS.  Results are cached for 30 days.
    """
    cached = _cache_read("historical_normals", ttl_hours=24 * 30)
    if cached:
        # Convert string keys back to int (JSON round-trip)
        try:
            return {int(k): tuple(v) for k, v in cached.items()}
        except (ValueError, TypeError):
            pass

    now = datetime.now()
    end_year = now.year - 1  # last complete year
    start_year = end_year - 4  # 5 years of data

    data = http_get_json(
        OPEN_METEO_HISTORICAL_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": f"{start_year}-01-01",
            "end_date": f"{end_year}-12-31",
            "daily": "temperature_2m_max,temperature_2m_min",
            "temperature_unit": "fahrenheit",
            "timezone": "auto",
        },
        timeout=15,
        label="Open-Meteo historical normals",
    )
    if data is None:
        return None

    daily = data.get("daily", {})
    times = daily.get("time", [])
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])

    if not times or len(times) != len(highs) or len(times) != len(lows):
        log.warning("weather: historical normals response malformed")
        return None

    # Accumulate by month
    month_hi: dict[int, list[float]] = {m: [] for m in range(1, 13)}
    month_lo: dict[int, list[float]] = {m: [] for m in range(1, 13)}
    for date_str, hi, lo in zip(times, highs, lows):
        if hi is None or lo is None:
            continue
        month = int(date_str[5:7])
        month_hi[month].append(hi)
        month_lo[month].append(lo)

    normals: dict[int, tuple[float, float]] = {}
    for m in range(1, 13):
        if not month_hi[m] or not month_lo[m]:
            log.warning(f"weather: no historical data for month {m}")
            return None
        avg_hi = sum(month_hi[m]) / len(month_hi[m])
        avg_lo = sum(month_lo[m]) / len(month_lo[m])
        normals[m] = (round(avg_hi, 1), round(avg_lo, 1))

    # Cache as string-keyed dict (JSON requires string keys)
    _cache_write("historical_normals", {str(k): list(v) for k, v in normals.items()})
    log.info("weather: fetched and cached historical normals")
    return normals


def _interpolate_monthly(table: dict, dt: datetime) -> tuple[float, float]:
    """Linearly interpolate between monthly values for a given date.

    Uses the 15th of each month as anchor points. Dates before the 15th
    interpolate between the previous month's 15th and the current month's 15th.
    Dates on/after the 15th interpolate between the current month's 15th and
    the next month's 15th.
    """
    month = dt.month
    day = dt.day

    # Decide which two anchor months to use
    if day >= 15:
        # Interpolate between this month's 15th and next month's 15th
        anchor_a = month
        anchor_b = month + 1 if month < 12 else 1
        year_a = dt.year
        year_b = dt.year if month < 12 else dt.year + 1
    else:
        # Interpolate between previous month's 15th and this month's 15th
        anchor_a = month - 1 if month > 1 else 12
        anchor_b = month
        year_a = dt.year if month > 1 else dt.year - 1
        year_b = dt.year

    hi_a, lo_a = table[anchor_a]
    hi_b, lo_b = table[anchor_b]

    day_15_a = datetime(year_a, anchor_a, 15).timetuple().tm_yday
    day_15_b = datetime(year_b, anchor_b, 15).timetuple().tm_yday
    day_of_year = dt.timetuple().tm_yday

    # Handle year boundary for day-of-year arithmetic
    if day_15_b < day_15_a:
        days_in_range = (365 - day_15_a) + day_15_b
        frac = (
            ((365 - day_15_a) + day_of_year) / days_in_range
            if day_of_year < day_15_b
            else (day_of_year - day_15_a) / (365 - day_15_a + day_15_b)
        )
    else:
        frac = (day_of_year - day_15_a) / (day_15_b - day_15_a)

    frac = max(0.0, min(1.0, frac))
    hi = hi_a + frac * (hi_b - hi_a)
    lo = lo_a + frac * (lo_b - lo_a)

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
    return aqi_label(aqi)


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
