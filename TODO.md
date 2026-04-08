# Morning Digest — TODO

_Last updated: 2026-04-08_

---

## Done this session

### Bug fixes
- **`--force-friday` was broken** — only passed to `synthesize` (dead stage). Fixed: now passed to `cross_domain` in `pipeline.py`; `cross_domain.py` updated to accept `force_friday` kwarg and pass it to `_build_input`.
- **Press release filter** — `stages/prepare_local.py` now filters items with `/press_releases/` in URL or PRNewswire/BusinessWire markers in summary.
  - **Bonus bug found and fixed**: `PRNewswire` (without slashes) wasn't caught in summaries. Changed `/PRNewswire/` → `PRNewswire` in `_WIRE_MARKERS`.

### UI / template improvements
- **At-a-glance voice labels** — Added SOURCES / ANALYSIS / THREAD micro-labels to each context block with distinct colors and a left-border visual separator for Analysis and Thread blocks.
- **AQI alert colors** — EPA-correct: red `#d32f2f` (Unhealthy 151–200), purple `#8f3f97` (Very Unhealthy 201–300), maroon `#7e0023` (Hazardous 301+). Previously all used `var(--down)` (always red).
- **AQI in weather bar** — Current AQI and label now shown inline in the weather bar: `Logan, UT — Clear · AQI 51 (Moderate)`.
- **Section order** — Moved Perspective Seams to follow Deep Dives (was between Cache Valley and Deep Dives).
- **Theme toggle** — Now injected inside `.wrapper` so it aligns with content; styled to match the dark chrome header instead of floating above the page.

### Code cleanup
- **`_cross_domain_item_to_glance` + `_domain_item_to_glance` merged** into `_item_to_glance` in `stages/assemble.py`. Aliases kept for safety.
- **`stages/synthesize.py` and `digest.py`** — Deleted (confirmed dead code, neither in `config.yaml` pipeline manifest). References cleaned from `pipeline.py`.
- **Prompt files moved to `prompts/`** — `chat_briefer_prompt.md`, `weather-display-prompt.md`, `scripture_study_prompt.md`, `morning-digest-v2-plan.md` relocated and naming standardized to snake_case.
- **`modules/` directory created** — `modules/__init__.py` in place for weather Phase 2.
- **`pytest>=8.0` added to `requirements.txt`**.
- **`tests/` skeleton created** — `tests/__init__.py`, `tests/conftest.py`, `tests/test_prepare_local.py` (9 passing tests covering press release filter).
- **Git hygiene verified** — `output/` and `__pycache__/` properly ignored; no tracked runtime artifacts.
- **Configuration polish** — FreshRSS placeholder fields now have clarifying comments; `to_address` comment generalized from "your gmail address" to "your email address".

### AQI editorial comment (weather spec)
- Added Utah DEQ action level language to `prompts/weather-display-prompt.md` Zone 1 spec.

---

## Next: Weather Display Module

Full implementation plan in `prompts/weather-display-prompt.md`. Summary of phases:

### Phase 0 — Prep (do first)
- [ ] Add `AIRNOW_API_KEY=` to `.env` (you have the key) and `.env.example`
- [ ] Expand `config.yaml` `weather:` block with `nws_station`, `airnow_api_key`, display flags
- [ ] Add `RUN mkdir -p /app/cache/weather` to `Dockerfile`
- [ ] Add `cache/weather/*.json` to `.gitignore`

### Phase 1 — Data layer (`sources/weather.py`)
Rewrite to use NWS as primary, Open-Meteo as silent fallback.

New functions:
- [ ] `_fetch_nws(lat, lon, nws_station)` — 2 NWS endpoints, 2-hour cache, `User-Agent` header required
- [ ] `_fetch_airnow_forecast(lat, lon, api_key)` → `{"YYYY-MM-DD": {"aqi": N, "aqi_label": "..."}}`, 1-hour cache
- [ ] `_compute_normals_and_records(dates)` — pure, uses hardcoded NOAA monthly tables from spec
- [ ] `_cache_read / _cache_write` — JSON files in `cache/weather/` with TTL
- [ ] Expand forecast day dicts: `precip_type`, `precip_timing`, `short_forecast`, `detailed_forecast`, `wind_speed`, `wind_direction`, `aqi`, `aqi_label`
- [ ] Add top-level: `humidity`, `wind_direction`, `aqi_forecast`, `normals`
- [ ] `_classify_precip()` and `_extract_precip_timing()` from spec (verbatim)

Key decisions:
- NWS covers all data needs for Logan UT. No dual-source needed for display data.
- AQI forecast days beyond AirNow range → gray `--` bars (not green). Never assume Good.
- Normals/records from hardcoded Logan NOAA tables with linear monthly interpolation.

### Phase 2 — SVG renderer (`modules/weather_display.py`) — new file
`modules/__init__.py` already created.

Public API:
```python
def render_weather_html(weather: dict, config: dict) -> str
```

Architecture:
- **Adaptive theme**: Add `--wx-*` CSS variables to all 4 theme blocks in `email_template.py`. SVG elements reference `var(--wx-hi)` etc. — CSS custom properties propagate into inline SVG in HTML DOM.
- **EPA AQI colors**: Hardcoded (regulatory, not aesthetic). `#00e400` / `#ffff00` / `#ff7e00` / `#ff0000` / `#8f3f97` / `#7e0023`.
- **SVG**: Pure f-string building, no library. `viewBox="0 0 640 230"`. Email safe: no `<use>`, `<symbol>`, `<script>`.

Zone layout (Y coordinates):
```
Zone 2 (temp chart):  y  8–128
Zone 3 (AQI strip):   y  133–143
Zone 4 (precip bars): baseline 190, grows upward
Zone 5 (day labels):  y  194–228
```

Zone renderers to implement:
- [ ] `_render_defs()` — 5 `<linearGradient>` elements (rain, snow, mix, thunder, freezing)
- [ ] `_render_zone2_gridlines()` — 4–5 horizontal gridlines, Y-axis temp labels
- [ ] `_render_zone2_bands()` — record band, normal band, forecast band
- [ ] `_render_zone2_lines()` — high line (solid amber), low line (dashed blue), dots, labels
  - If forecast temp within 2°F of record: larger dot + glow
- [ ] `_render_zone3_aqi()` — one rect per day, EPA colors, `--` for missing
- [ ] `_render_zone4_precip()` — bars by type, ⚡ ❄ `mix` `frz` markers
- [ ] `_render_zone5_labels()` — day abbrev + condition text
- [ ] `_render_header_html()` — Zone 1 text header (includes AQI editorial for ≥151)
- [ ] `_render_legend_html()` — colored swatches row
- [ ] Fallback chain: empty weather → `""`, insufficient data → text-only header, SVG exception → text-only header

### Phase 3 — Integration
- [ ] `stages/prepare_weather.py` — call `render_weather_html()`, return `weather_html`
- [ ] `stages/assemble.py` — add `weather_html: Markup(...)` to template_data
- [ ] `templates/email_template.py`:
  - Add `--wx-*` CSS variables to all 4 theme blocks
  - Add `.wx-bg`, `.wx-hi`, `.wx-lo` etc. CSS class rules
  - Replace `<!-- WEATHER -->` block with `{% if weather_html %}...{% elif weather %}...{% endif %}`
  - Add Google Fonts `@import` (first line inside `<style>`) for JetBrains Mono + DM Sans

### Phase 4 — Tests
`tests/` directory created with `test_prepare_local.py` (9 passing tests).

Remaining test files to create:
- [ ] `tests/fixtures/` with 7 weather JSON fixtures:
  - `weather_clear.json` — copy from `output/artifacts/2026-04-07/weather.json`
  - `weather_inversion.json` — AQI 175, flat temps, no precip (Jan/Feb pattern)
  - `weather_snow.json` — precip_type=snow, AQI moderate
  - `weather_thunderstorm.json` — PM thunderstorm, summer
  - `weather_mixed.json` — rain/snow mix transition
  - `weather_minimal.json` — minimal fields (Open-Meteo fallback simulation)
  - `weather_missing_aqi.json` — all AQI values None
- [ ] `tests/test_weather_classify.py` — `_classify_precip`, `_extract_precip_timing`
- [ ] `tests/test_weather_normals.py` — interpolation math
- [ ] `tests/test_weather_display.py` — coord math, AQI color mapping, SVG structure
- [ ] `tests/test_weather_integration.py` — full fixture → render → validate HTML

Run tests inside Docker (after rebuild):
```bash
docker compose run --rm morning-digest python -m pytest tests/ -v
```

### Phase 5 — Supporting file updates
- [ ] `README.md`:
  - Add AirNow to API keys table
  - Update data sources list (NWS replaces Open-Meteo)
  - Add `modules/weather_display.py` and `tests/` to file tree
  - Add "Running Tests" section
  - Update Dark Mode section to mention SVG adaptive theming
- [ ] `prompts/weather-display-prompt.md` — Add adaptive SVG note (CSS variables, not hardcoded dark)

---

## Other open items

### Docker rebuild reminder
Code changes require a rebuild — only `config.yaml` and `output/` are volume-mounted:
```bash
docker compose build && docker compose up -d
```

### `.env` — add when starting weather Phase 0
```
AIRNOW_API_KEY=<your_key>
```
