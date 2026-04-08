# Weather Display Implementation — Sparkline B2 with AQI Strip

## What This Is

Implement a 7-day weather forecast SVG display for the Morning Digest email briefing. The display is a single inline SVG embedded in an HTML email. It must render correctly in email clients (Gmail, Apple Mail, Proton Mail).

## Visual Design Specification

The display has four vertical zones, top to bottom:

### Zone 1: Header (text, not SVG)
- Location, current temp, current condition, current AQI, wind, humidity
- Example: `Logan, UT · 49°F Clear · AQI 26 (Good) · Wind calm · Humidity 54%`
- Right-aligned: current date
- When current AQI is Unhealthy (151) or worse, display a one-sentence editorial comment
  on the line below the header, using Utah DEQ action level language:
  - 151–200 Unhealthy (Red): "Red Action Day — everyone should limit prolonged outdoor activity."
  - 201–300 Very Unhealthy (Purple): "Purple Action Day — avoid prolonged outdoor activity; sensitive groups should stay indoors."
  - 301+ Hazardous (Maroon): "Maroon Action Day — Hazardous. Everyone should avoid all outdoor activity."
  - Style this line in the AQI category color (see Zone 3 palette) so it draws the eye.

### Zone 2: Temperature Chart (SVG, ~120px tall)
Three background layers (bottom to top):
1. **Record range band**: Faint white/transparent rectangle spanning the daily record high to record low for the 7-day window. Label right edge with `REC` markers.
2. **Normal range band**: Green-tinted rectangle spanning the daily normal high to normal low. Label right edge with normal values (e.g., `57°n`, `33°n`).
3. **Forecast band**: Semi-transparent fill between the high and low lines.

Two data lines:
- **High line**: Solid, warm amber (#d09050), 2px, with dots at each day and temperature labels above each dot.
- **Low line**: Dashed, cool blue (#5a7aa0), 1.5px, with dots and temperature labels below each dot.

X-axis: 7 equally-spaced day positions. Y-axis: left side, temperature scale with 4-5 gridlines.

### Zone 3: AQI Strip (SVG, ~10px tall)
- One colored rectangle per day, colored by EPA AQI category:
  - 0-50 Good: #00e400, low opacity (~0.15)
  - 51-100 Moderate: #ffff00, opacity ~0.3
  - 101-150 USG: #ff7e00, opacity ~0.45
  - 151-200 Unhealthy: #ff0000, opacity ~0.5
  - 201-300 Very Unhealthy: #8f3f97, opacity ~0.55
  - 301+ Hazardous: #7e0023, opacity ~0.6
- AQI numeric value as text INSIDE each colored rectangle, colored to match but lighter for readability.
- Left label: `AQI` in small monospace.
- When AQI is Good all week, the strip should be subtle (thin, low opacity) but still present.
- When any day is Moderate or worse, increase strip height from 6px to 10px for the whole row.

### Zone 4: Precipitation Bars (SVG, variable height, growing upward from baseline)
- Bar height proportional to precipitation probability (0-100%).
- Bar gradient by precipitation type:
  - **Rain only**: Blue gradient (#5b9bd5), bottom-opaque to top-transparent.
  - **Thunderstorm**: Blue-to-purple-to-amber gradient with faint amber (#c8a44a) stroke. Add ⚡ marker below bar.
  - **Snow**: Blue gradient with white/ice tint (#a0d4f0). Add ❄ marker below bar.
  - **Rain/snow mix**: Split gradient, blue lower half transitioning to ice-white upper half. Add 🌨 or `mix` label.
  - **Freezing rain**: Blue gradient with red-orange (#e06040) stroke (danger signal). Add `frz` label.
- Probability percentage label above each bar.
- Days with 0% probability: no bar, no label.

### Zone 5: Day Labels and Conditions (SVG text)
- Day abbreviation in monospace: `TUE`, `WED`, etc.
- Condition summary below in sans-serif: `Sunny`, `Shwrs PM`, `Snow Lkly`, etc.

## Legend
Render a small legend row between header and SVG with colored swatches for: Forecast Hi, Forecast Lo, Normal range, Record range, Precip, ⚡Tstorm, AQI scale.

## Typography
- Labels and data: `JetBrains Mono` (monospace), sizes 7-9px in SVG.
- Conditions: `DM Sans` (sans-serif), size 7px.
- Import both via Google Fonts in the HTML wrapper.

## Color Palette (dark theme for email)
- Background: #0f0f12
- Card border: #252528
- Grid lines: #1e1e22
- Label text: #555 (secondary), #444 (tertiary)
- High line: #d09050
- Low line: #5a7aa0
- Normal band: rgba(100,160,100,0.18) to rgba(100,160,100,0.06)
- Record band: rgba(255,255,255,0.04) to rgba(255,255,255,0.01)
- Precip blue: #5b9bd5
- AQI: EPA standard colors listed above

## Data Sources

### Temperature Forecast
**Primary: NWS API (free, no key required)**
- Endpoint: `https://api.weather.gov/points/41.7369,-111.8348` → follow `forecast` link
- Returns 14 periods (day/night pairs for 7 days) with temperature, shortForecast, detailedForecast, probabilityOfPrecipitation, windSpeed, windDirection.
- Parse `shortForecast` for condition type (contains keywords like "Sunny", "Showers", "Snow", "Thunderstorms").
- Parse `detailedForecast` for timing info ("after noon", "before 11pm", "mainly in the morning").
- Rate limit: be polite, cache aggressively. Set `User-Agent` header to identify the application per NWS API policy.

**Fallback: Open-Meteo (free, no key)**
- Endpoint: `https://api.open-meteo.com/v1/forecast?latitude=41.7369&longitude=-111.8348&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,snowfall_sum,weathercode&temperature_unit=fahrenheit&timezone=America/Denver`
- Provides precipitation_sum (mm) for intensity and snowfall_sum for snow detection.
- Weather codes map to condition types (WMO standard).

### Normal Temperatures
**Primary: Open-Meteo Climate API**
- Endpoint: `https://climate-api.open-meteo.com/v1/climate?latitude=41.7369&longitude=-111.8348&daily=temperature_2m_max_mean,temperature_2m_min_mean&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&models=EC_Earth3P_HR&temperature_unit=fahrenheit`
- Query for the specific 7-day date range using climatological model.

**Fallback: Hardcoded monthly normals for Logan (NOAA 1991-2020)**
Use these as fallback if the API is unavailable. Interpolate linearly between months:
```
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
