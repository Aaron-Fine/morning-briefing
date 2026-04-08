# Weather Display Module — Implementation Guide

## Status: COMPLETE (Phases 0–4)

This document describes the implemented weather display system. All code is in production.

## Architecture Overview

The weather module consists of four components:

1. **Data Layer** (`sources/weather.py`) — Fetches from NWS (primary) with Open-Meteo fallback, AirNow AQI, NOAA normals/records
2. **SVG Renderer** (`modules/weather_display.py`) — `render_weather_html(weather, config) -> str`
3. **Pipeline Stage** (`stages/prepare_weather.py`) — Calls renderer, returns `{"weather": ..., "weather_html": ...}`
4. **Template Integration** (`templates/email_template.py`) — Embeds `weather_html` with `{% if weather_html %}` fallback

## File Structure

```
sources/
  weather.py            # Data fetching, caching, precip classification, normals
modules/
  weather_display.py    # SVG rendering, HTML generation
stages/
  prepare_weather.py    # Pipeline stage wrapper
tests/
  fixtures/
    weather_clear.json
    weather_inversion.json
    weather_snow.json
    weather_thunderstorm.json
    weather_mixed.json
    weather_minimal.json
    weather_missing_aqi.json
  test_weather_classify.py
  test_weather_display.py
  test_weather_integration.py
```

## Data Layer (`sources/weather.py`)

### Public API
```python
def fetch_weather(config: dict) -> dict:
    """Returns dict with keys:
    current_temp_f, condition, wind_mph, wind_direction, humidity,
    today_high_f, today_low_f, forecast: [day_dicts],
    city, state, aqi, aqi_label, pm2_5, pm10,
    aqi_forecast: {date_str: {aqi, aqi_label}},
    normals: [{date, normal_hi, normal_lo, record_hi, record_lo}]
    """
```

### Precipitation Classification
```python
def _classify_precip(short_forecast, detailed_forecast, temp_hi, temp_lo) -> str:
    """Returns: 'none', 'rain', 'snow', 'thunderstorm', 'mix', 'freezing_rain'"""

def _extract_precip_timing(detailed) -> str:
    """Returns: '', 'AM', 'PM', 'eve', 'night'"""
```

### Normals & Records
- NOAA 1991-2020 normals hardcoded for Logan, UT (month index 1-12)
- Linear interpolation between 15th of each month for daily resolution
- Year-boundary handling (December → January)

### Caching
- JSON files in `cache/weather/`
- 2hr TTL for NWS forecast, 1hr TTL for AQI data
- 24hr TTL for NWS points endpoint

## SVG Renderer (`modules/weather_display.py`)

### Public API
```python
def render_weather_html(weather: dict, config: dict) -> str:
    """Returns complete HTML block (header + legend + SVG) for embedding.
    
    Fallback chain:
    - empty weather → ""
    - insufficient data → text-only header
    - SVG exception → text-only fallback
    """
```

### SVG Layout (5 zones)
- **Zone 1**: Header div (location, temp, condition, AQI, wind, humidity)
- **Zone 2**: Temperature chart (record band, normal band, forecast fill, high/low lines)
- **Zone 3**: AQI strip (EPA-colored daily bars, `--` for missing data)
- **Zone 4**: Precipitation bars (type-specific gradients, probability labels, emoji markers)
- **Zone 5**: Day labels (abbreviations + condition summaries)

### Key Constants
```python
SVG_WIDTH = 640
SVG_HEIGHT = 230
ZONE2_TOP = 8
ZONE2_BOTTOM = 128
ZONE3_Y = 133
ZONE4_BASELINE = 190
ZONE5_Y = 194
DAY_COUNT = 7
DAY_SPACING = (SVG_WIDTH - 60) / DAY_COUNT
DAY_START_X = 50
```

### AQI Colors (EPA regulatory)
| Category | Color | Opacity |
|----------|-------|---------|
| Good | #00e400 | 0.15 |
| Moderate | #ffff00 | 0.30 |
| USG | #ff7e00 | 0.45 |
| Unhealthy | #ff0000 | 0.50 |
| Very Unhealthy | #8f3f97 | 0.55 |
| Hazardous | #7e0023 | 0.60 |

### Precipitation Gradients
| Type | Colors | Marker |
|------|--------|--------|
| rain | #5b9bd5 → transparent | — |
| thunderstorm | #5b9bd5 → #8f3f97 → #c8a44a | ⚡ |
| snow | #a0d4f0 → transparent | ❄ |
| mix | #5b9bd5 → #a0d4f0 | 🌨 |
| freezing_rain | #5b9bd5 → #e06040 | frz |

## Pipeline Integration

### prepare_weather stage
```python
def run(context, config, **kwargs) -> dict:
    """Input: context["raw_sources"]["weather"]
    Output: {"weather": <dict>, "weather_html": <str>}
    """
```

### assemble stage
- Receives `weather_html` from context
- Wraps in `Markup()` to bypass Jinja2 autoescape
- Passes to `render_email(template_data)`

### email_template.py
```jinja2
{% if weather_html %}
  {{ weather_html }}
{% elif weather %}
  <p>{{ weather.city }}, {{ weather.state }} — {{ weather.current_temp_f }}°F {{ weather.condition }}</p>
{% endif %}
```

## Configuration

```yaml
weather:
  enabled: true
  nws_station: "KLGU"
  aqi_strip: true
  record_band: true
  normal_band: true
```

Environment variables:
- `AIRNOW_API_KEY` — Optional, degrades to Open-Meteo AQI fallback

## Testing

Run all weather tests:
```bash
docker compose run --rm morning-digest python -m pytest tests/test_weather_*.py -v
```

109 tests across 3 test files:
- `test_weather_classify.py` — Precip classification and timing extraction
- `test_weather_display.py` — SVG rendering, helper functions, all 7 fixtures
- `test_weather_integration.py` — Full pipeline: prepare_weather → assemble → validate

## Email Compatibility

- Inline SVG only — no `<use>`, `<symbol>`, or external references
- `<defs>` with `<linearGradient>` works in modern email clients
- Google Fonts imported via `@import` (JetBrains Mono + DM Sans)
- Emoji characters (❄, ⚡, 🌨) render natively
- CSS variables (`--wx-*`) defined in all 4 theme blocks

## Cache Valley Edge Cases (Handled)

1. **Winter Inversions** — Flat temps, degrading AQI over days
2. **Rain/Snow Mix** — Split gradient bars with 🌨 marker
3. **Freezing Rain** — Blue-to-red gradient with "frz" label
4. **PM Thunderstorms** — ⚡ marker + "PM" timing label
5. **Missing AQI** — Thin gray `--` bars (never assumes "Good")
6. **Record-Breaking** — Dots highlighted when within 2°F of records
7. **NWS Failure** — Silent fallback to Open-Meteo
8. **All Sources Fail** — Text-only fallback instead of broken SVG
Month  Normal Hi  Normal Lo
Jan    28.8       14.0
Feb    31.5       17.8
Mar    40.3       25.5
Apr    48.6       30.9  (note: early Apr ~55-58 hi, ~31-34 lo by mid-month progression)
May    59.4       38.5
Jun    70.7       46.3
Jul    83.3       55.4
Aug    81.1       53.6
Sep    71.4       43.8
Oct    54.5       32.8
Nov    41.0       22.7
Dec    28.8       15.3
```
For daily resolution, interpolate between the 15th of each month.

### Record Temperatures
**Primary: Open-Meteo Historical API**
- Query historical data for the relevant dates across available years to find extremes.
- Alternatively, use NOAA LCD (Local Climatological Data) if available.

**Fallback: Hardcoded approximate monthly records for Logan**
```
Month  Record Hi  Record Lo
Jan    60         -25
Feb    63         -23
Mar    75         -5
Apr    82         10
May    93         18
Jun    100        28
Jul    103        35
Aug    101        32
Sep    97         16
Oct    85         2
Nov    73         -14
Dec    62         -20
```
For daily resolution, use the monthly value as the bound for any day in that month.

### Air Quality / AQI
**Primary: AirNow API (free, requires key — register at airnowapi.org)**
- Current: `https://www.airnowapi.org/aq/observation/latLong/current/?format=application/json&latitude=41.7369&longitude=-111.8348&distance=25&API_KEY=YOUR_KEY`
- Forecast: `https://www.airnowapi.org/aq/forecast/latLong/?format=application/json&latitude=41.7369&longitude=-111.8348&API_KEY=YOUR_KEY`
- Returns AQI value and category for PM2.5, Ozone, and overall.
- Forecast is typically 1-2 days out only.

**Secondary: Utah DEQ (air.utah.gov)**
- Cache County 3-day forecast: `https://air.utah.gov/forecast.php?id=sm`
- Scrape if no API is available. Provides action forecast (green/yellow/orange/red) and health forecast.
- This source understands Cache Valley inversion dynamics better than national sources.

**Fallback for days without AQI forecast:**
- If only 1-2 days of AQI forecast available, show data for those days and leave remaining days with a thin gray bar and `--` label (no data, not "good").
- Do NOT assume good AQI for unforecasted days during inversion season (Nov-Feb).

### Current Conditions
**Primary: NWS current observations**
- Station KLGU (Logan-Cache Airport): `https://api.weather.gov/stations/KLGU/observations/latest`
- Returns temperature, humidity, wind, barometric pressure, textDescription.

### Precipitation Type Detection
Parse from NWS `shortForecast` and `detailedForecast` fields using keyword matching:

```python
def classify_precip(short_forecast: str, detailed_forecast: str, temp_hi: float, temp_lo: float) -> str:
    text = (short_forecast + " " + detailed_forecast).lower()

    has_thunder = any(w in text for w in ["thunderstorm", "thunder", "t-storm"])
    has_snow = any(w in text for w in ["snow", "flurries", "blizzard", "winter storm"])
    has_rain = any(w in text for w in ["rain", "shower", "drizzle", "precipitation"])
    has_freezing = any(w in text for w in ["freezing rain", "ice", "sleet", "freezing drizzle"])
    has_mix = any(w in text for w in ["rain and snow", "snow and rain", "mix", "wintry mix"])

    if has_freezing:
        return "freezing_rain"  # highest priority — danger signal
    if has_mix or (has_snow and has_rain):
        return "mix"
    if has_thunder:
        return "thunderstorm"
    if has_snow:
        return "snow"
    if has_rain:
        return "rain"
    return "none"
```

### Precipitation Timing Detection
Parse `detailedForecast` for timing keywords:

```python
def extract_precip_timing(detailed: str) -> str:
    text = detailed.lower()
    if "after noon" in text or "in the afternoon" in text:
        return "PM"
    if "before noon" in text or "in the morning" in text:
        return "AM"
    if "in the evening" in text or "after midnight" in text:
        return "eve"
    if "mainly" in text and "night" in text:
        return "night"
    return ""  # all day or unspecified
```

## Cache Valley Edge Cases

Cache Valley has specific meteorological patterns that must be handled correctly:

### 1. Winter Inversions (Nov-Feb, occasionally Oct and Mar)
- **Pattern**: Multi-day stagnation events where cold air pools in the valley, AQI degrades daily until a storm breaks it.
- **Visual behavior**: AQI strip transitions from green → yellow → orange → red → purple over 3-7 days. When storm arrives, precip bars appear and AQI drops back to green within 1-2 days.
- **Data note**: During inversions, valley floor temps may be COLDER than mountain temps. NWS forecast is for the valley floor (KLGU elevation 4446ft). The temperature chart may show unusually flat or slightly warming highs during inversions as the inversion cap warms — this is correct, do not "fix" it.

### 2. Temperature Inversions Without Poor AQI
- Spring/fall can have overnight inversions (valley fog) without PM2.5 buildup. AQI stays green but conditions show "Fog" or "Haze".
- Handle: Show the condition text ("Fog") but keep AQI strip green if AQI data confirms it's fine.

### 3. Rain/Snow Transition Days
- Extremely common in Cache Valley spring (Mar-May) and fall (Oct-Nov). A single day may start with snow and transition to rain, or vice versa.
- NWS `detailedForecast` will say things like "Snow, changing to rain in the afternoon" or "Rain and snow likely before noon, then rain likely".
- **Handle**: Use the `mix` bar style. If the `detailedForecast` specifies a transition, append timing: `Snow→Rain PM`.

### 4. Lake Effect / Orographic Enhancement
- Great Salt Lake and Bear River Range can amplify snowfall beyond what regional models predict. NWS will sometimes note "locally higher amounts" or "orographic enhancement".
- **Handle**: If `detailedForecast` mentions accumulation amounts, show them as a small label beneath the snow marker (e.g., `2-4"`).

### 5. Wind Events
- Cache Valley gets occasional strong canyon winds (east winds from Logan Canyon, south winds from Sardine Canyon).
- NWS forecasts include wind speed and gusts. If wind > 25mph or gusts > 40mph, consider adding a wind indicator (small arrow or `💨` marker) — but this is lower priority than the core display.

### 6. Thunderstorm Season (May-Sep)
- Afternoon convective storms are common in summer. These are almost always PM-only events.
- **Handle**: The ⚡ thunderstorm bar style + timing label ("PM") handles this well.

### 7. Days Where Precip AND Poor AQI Coexist
- Rare but possible: a weak system arrives that produces light precipitation but doesn't fully break an inversion.
- **Handle**: B2's separate lanes handle this correctly by design — the AQI strip shows orange/red while a small precip bar also appears. No special code needed, just don't assume precip always means clean air.

### 8. Smoke Events (Summer)
- Wildfire smoke from Western fires can produce multi-day high-AQI events in summer with no precipitation and no inversion.
- **Handle**: AQI strip shows orange/red/purple, precip bars are absent. The AQI data from AirNow will correctly reflect PM2.5 from smoke. No special logic needed — the B2 layout handles this naturally because AQI has its own lane.

### 9. Record-Breaking Days
- When a forecast high or low exceeds or approaches the record range band, it should be visually obvious — the dot will be at or outside the record band edge.
- **Handle**: If forecast temp is within 2°F of a record, consider highlighting the dot (larger radius, or a subtle glow). If it exceeds the record, extend the record band to include it so the dot isn't clipped.

### 10. Missing or Stale Data
- NWS API occasionally returns 500 errors or stale data.
- AQI forecast may only cover 1-2 days.
- **Handle**:
  - If NWS fails, fall back to Open-Meteo.
  - If AQI data is missing for a day, render a thin gray bar with `--` label. Do not render green (that implies Good, which is a claim about air quality).
  - If all data sources fail, skip the weather display entirely rather than rendering with stale data. Add a one-line text fallback: "Weather data temporarily unavailable."
  - Cache fetched data with a TTL of 2 hours. The digest runs once daily so this is mainly for retry resilience.

## Implementation Notes

### SVG Construction
Build the SVG as a Python string template or with an SVG builder library. The entire display is a single `<svg>` element with a fixed `viewBox` (e.g., `0 0 640 230`). All elements are positioned absolutely within the viewBox.

The Y-axis mapping function:
```python
def temp_to_y(temp: float, temp_min: float, temp_max: float, y_top: float = 10, y_bottom: float = 120) -> float:
    """Map temperature to SVG y-coordinate. Higher temp = lower y (higher on screen)."""
    return y_top + (temp_max - temp) * (y_bottom - y_top) / (temp_max - temp_min)
```

Set `temp_min` and `temp_max` to the record low and record high for the 7-day window (with some padding), so the record band fills the full chart height.

### Precip bar height:
```python
def precip_to_height(probability_pct: float, max_height: float = 45) -> float:
    return probability_pct / 100.0 * max_height
```

### Email Compatibility
- Inline SVG works in Gmail, Apple Mail, and Proton Mail.
- Do NOT use `<use>`, `<symbol>`, or external references — some email clients strip these.
- `<defs>` with `<linearGradient>` works in most modern email clients. For maximum compatibility, consider a fallback that uses flat colors instead of gradients.
- Google Fonts: import in the HTML `<style>` block wrapping the SVG. Email clients that strip `<style>` will fall back to system fonts — this is acceptable.
- Emoji characters (❄, ⚡, 🌨) render natively in email clients. They are not images.
- Test with `htmlemailcheck.com` or Litmus if available.

### File Location
This should be a module within the Morning Digest pipeline. Suggested path: `modules/weather_display.py` with a function signature like:

```python
def render_weather_svg(
    location: str,
    lat: float,
    lon: float,
    nws_station: str,  # e.g., "KLGU"
    airnow_api_key: str | None = None,
) -> str:
    """Fetch weather data and return complete HTML block (header + SVG) for embedding in digest email."""
```

### Caching Strategy
- Cache NWS forecast response for 2 hours.
- Cache AQI data for 1 hour.
- Cache normals/records indefinitely (they don't change).
- Store cache as JSON files in a `cache/` directory alongside the digest pipeline.

### Configuration
Add to the digest config:
```yaml
weather:
  enabled: true
  location: "Logan, UT"
  lat: 41.7369
  lon: -111.8348
  nws_station: "KLGU"
  airnow_api_key: "${AIRNOW_API_KEY}"  # optional, degrades gracefully
  aqi_strip: true  # can disable for non-valley locations
  record_band: true
  normal_band: true
  dark_theme: true
```
